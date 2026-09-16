# Daniel visitor-journey observability

Sugarkube owns only the scheduling descriptor, bounded aggregate metric conversion, dashboards, and
alerts for the application-owned `danielsmith.io` visitor journey. The application continues to own
all browser assertions. Sugarkube does not repeat homepage, JavaScript, asset, accessible fallback,
résumé PDF, or immersive-rendering assertions.

Both staging and production descriptors are disabled. Activation requires separate authorization
and qualification of the request multiplicity; validation fails closed if an enabled descriptor has
no such bound. The five-minute cadence, 30-second timeout, concurrency of one, quota limits, and
safety margin are declarations only and do not install or execute a timer.

The converter accepts exactly `state`, `freshness`, `aggregateDurationMs`, and `failureStage` from
the application contract. It rejects extra fields, non-finite or negative values, contradictory
success/failure stages, and unknown stages. Its lifecycle distinguishes `disabled`, `unavailable`,
`stale`, `failed`, `recovered`, and `successful`. A disabled producer emits no success series.
Optional immersive-renderer state is exported separately and never participates in the essential
journey alerts.

No visitor data, request identity, page or response body, headers, cookies, credentials, URLs, or
unbounded exception text are accepted as labels or metric values. These definitions do not establish
staging or production readiness and must not be used as authorization to activate either producer.
