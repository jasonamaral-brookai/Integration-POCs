# PAI-416: Wire ExponentialBackoffInterceptor into AthenaApiService and RedoxApiService

**PROPOSAL — not a PR. For Brook Backend team review.**

Linear: https://linear.app/brook-health/issue/PAI-416/p0-wire-exponentialbackoffinterceptor-into-athenaapiservice-and

`ExponentialBackoffInterceptor.java` exists in brook-backend and is confirmed to handle
HTTP 429 + `Retry-After` correctly. It is not added to either production OkHttp client
builder. This proposal shows the two-line wiring change for each service and the
recommended test shape.

---

## 1. AthenaApiService — proposed change

The `AthenaApiService` OkHttp client builder currently looks approximately like this
(path: `src/main/java/ai/brook/service/athena/AthenaApiService.java`):

```java
@Bean
public OkHttpClient athenaHttpClient() {
    return new OkHttpClient.Builder()
            .connectTimeout(30, TimeUnit.SECONDS)
            .readTimeout(30, TimeUnit.SECONDS)
            .addInterceptor(authInterceptor)          // existing auth interceptor
            .build();
}
```

**Proposed change — add ExponentialBackoffInterceptor:**

```java
@Bean
public OkHttpClient athenaHttpClient(
        AuthInterceptor authInterceptor,
        ExponentialBackoffInterceptor backoffInterceptor) {  // inject existing bean
    return new OkHttpClient.Builder()
            .connectTimeout(30, TimeUnit.SECONDS)
            .readTimeout(30, TimeUnit.SECONDS)
            .addInterceptor(authInterceptor)
            .addInterceptor(backoffInterceptor)        // wire here — order matters: auth first
            .build();
}
```

**Why auth before backoff:** The backoff interceptor retries the full request chain.
Auth needs to run on each retry attempt so that a token refreshed mid-backoff is
used on the next try. Auth interceptor must be inner (closer to the network).

---

## 2. RedoxApiService — proposed change

Same pattern. Path: `src/main/java/ai/brook/service/redox/RedoxApiService.java`
(or wherever the Redox OkHttp client is constructed — recon found it in
`RedoxService.java`; confirm exact location before applying).

```java
@Bean
public OkHttpClient redoxHttpClient(
        RedoxAuthInterceptor redoxAuthInterceptor,
        ExponentialBackoffInterceptor backoffInterceptor) {
    return new OkHttpClient.Builder()
            .connectTimeout(30, TimeUnit.SECONDS)
            .readTimeout(30, TimeUnit.SECONDS)
            .addInterceptor(redoxAuthInterceptor)
            .addInterceptor(backoffInterceptor)
            .build();
}
```

---

## 3. ExponentialBackoffInterceptor — current shape (for reference)

Recon confirmed this class exists. Key behavior:

- On HTTP 429: reads `Retry-After` header value (seconds), sleeps, then retries
- If no `Retry-After` header: falls back to exponential backoff (base delay * 2^attempt)
- Does NOT affect `ReactUtils.retryWithExponentialBackoff` — that is RxJava3 retry
  for reactive streams; this interceptor handles OkHttp synchronous calls only

No changes to `ExponentialBackoffInterceptor.java` are required by this ticket.

---

## 4. Recommended test

Add to `AthenaApiServiceTest.java` (or create if it does not exist):

```java
@Test
void athenaClient_retries_on_429_with_retry_after_header() throws Exception {
    // Arrange: mock server returns 429 once, then 200
    MockWebServer server = new MockWebServer();
    server.enqueue(new MockResponse()
            .setResponseCode(429)
            .addHeader("Retry-After", "1"));   // 1 second
    server.enqueue(new MockResponse()
            .setResponseCode(200)
            .setBody("{\"result\": \"ok\"}"));
    server.start();

    OkHttpClient client = new OkHttpClient.Builder()
            .addInterceptor(new ExponentialBackoffInterceptor())
            .build();

    Request request = new Request.Builder()
            .url(server.url("/test"))
            .build();

    long start = System.currentTimeMillis();
    Response response = client.newCall(request).execute();
    long elapsed = System.currentTimeMillis() - start;

    // Assert: second request succeeded
    assertThat(response.code()).isEqualTo(200);

    // Assert: interceptor waited at least Retry-After seconds before retrying
    assertThat(elapsed).isGreaterThanOrEqualTo(1000L);

    // Assert: exactly two requests were made (one 429, one 200)
    assertThat(server.getRequestCount()).isEqualTo(2);

    server.shutdown();
}
```

Add an equivalent test for `RedoxApiService`.

**Dependency:** `MockWebServer` is already in brook-backend's test dependencies
(OkHttp test artifacts). No new test dependency required.

---

## 5. Notes for the implementing engineer

- `ExponentialBackoffInterceptor` should be a Spring `@Component` (singleton).
  Confirm it is annotated before injecting — if it is a plain class today, add
  `@Component` as part of this ticket.
- The interceptor is stateless (no per-request mutable fields), so singleton
  scope is safe for concurrent OkHttp calls.
- Do not add the interceptor to any OkHttp clients used for non-EMR calls
  (e.g., internal Brook service calls). Scope to athena and Redox clients only.
- `ReactUtils.retryWithExponentialBackoff` callsites are unaffected by this change.
  Do not modify them.
