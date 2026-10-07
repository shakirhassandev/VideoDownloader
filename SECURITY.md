# Security notes for a public downloader

A public arbitrary-URL downloader is an abuse-sensitive service. The application includes basic protections, but application code alone is not enough for a high-traffic public deployment.

## Included

- HTTP/HTTPS URL-only validation
- DNS resolution check before extraction
- Blocking of obvious loopback, private, link-local, multicast, reserved and unspecified addresses
- No embedded URL credentials
- No browser-cookie import or user-supplied authentication tokens
- No DRM-decryption path
- Playlist disabled by default
- Duration and file-size limits
- Concurrency limits
- Per-IP request throttling
- Temporary-file expiry
- Safe server-generated job IDs
- Client cannot submit arbitrary yt-dlp format expressions

## Still required at infrastructure level

Because remote sites can redirect or DNS answers can change, enforce egress restrictions outside the application too. The downloader process/container should not be able to reach:

- 127.0.0.0/8
- 10.0.0.0/8
- 172.16.0.0/12
- 192.168.0.0/16
- 169.254.0.0/16
- ::1/128
- fc00::/7
- fe80::/10
- cloud metadata endpoints
- database/admin networks

Put the service behind HTTPS, a reverse proxy/CDN, request-rate controls and server monitoring. If you scale past one API instance, move rate limits and job metadata to shared infrastructure such as Redis.
