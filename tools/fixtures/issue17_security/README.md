# Synthetic privacy fixtures

All markers are artificial. The native driver links the candidate Query formatter,
TDLib header serializer and the production privacy sink before file/memory output.
It verifies private bytes remain in the HTTP header while logs omit them. It does
not prove Telegram authorization or end-to-end webhook delivery. Candidate build,
actual binary smoke and source revision are independently required by the gate.

Source/sink map at the pinned revision:

- Query.cpp: general query formatter and response logging use counts/status.
- Client.cpp: webhook log and actor name omit the persisted value; database value
  construction and the secret passed to WebhookActor remain unchanged.
- WebhookActor.cpp: constructor/header/response logs omit private payloads;
  HttpHeaderCreator still receives the original secret and URL.
- HttpConnection.cpp: request/result logging uses fixed events and counts.
- telegram-bot-api.cpp / TDLib LogInterface: PrivacyLog runs before CombinedLog,
  AsyncFileLog and MemoryLog. Signal dumps see projected memory; actor tags and
  debugger locals are withheld. Levels 0..3 cover fatal/error/warning/info;
  debug/VLOG escalation is rejected or clamped.

The driver covers the production Query formatter and HTTP header serializer,
plus capture/memory sinks. Native file logs and memory dump require the explicit
exact-image gate. Client database persistence is not an authorization/delivery
fixture; no real Telegram credentials are used.
