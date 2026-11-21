# The site's certificate

**No domain and no certificate exist yet.** The proxy is ready for either
of the two usual ways; which one is the founder's choice with the domain
(F-17, and Cloudflare, blueprint M.2: Proposed). Until then automatic
renewal is **off** (`MARKX_TLS_RENEWAL=none` in `compose.env`, D-103).

A certificate can no longer expire silently (D-103): whatever renews it,
or fails to, **the worker's watch reads the date the proxy's certificate
really expires** and raises an alert 21 days before (`MARKX_TLS_WARN_DAYS`,
PROVISIONAL P-103-1), critical in the last 7 days and once expired. The
alert goes where every operations alert goes: the founder's Telegram group
once it exists, the log until then. It resolves on its own once a renewed
certificate is in place.

The proxy reads, read-only, from `MARKX_TLS_DIR` (default `/etc/markx/tls`,
mode 755):

| File | Owner and mode | What |
| --- | --- | --- |
| `fullchain.pem` | root, 644 | the certificate and its chain; the worker reads it (read-only) for its expiry date |
| `privkey.pem` | uid 101 (the proxy's user), 400 | the private key; nobody else may read it (the worker, uid 999, cannot: the rehearsal checks) |

`deploy.sh check` refuses anything else, a key that is not the
certificate's own, a certificate that does not name `MARKX_SITE_HOSTNAME`,
and an expired one; it warns inside the warning time.

## Putting a certificate in place (every option)

```bash
infra/production/deploy.sh certificate install /path/to/folder   # holds fullchain.pem and privkey.pem
```

It checks the new pair first (parses, the key matches, the hostname, at
least one more day of validity) and refuses it otherwise, leaving the
current one unchanged. Then it writes both files with the owners above,
renames them over the old ones, and has the proxy test its configuration
and **reload without a restart**. If the proxy refuses, the previous
certificate is put back. **Tested** by the rehearsal (a wrong hostname and a
wrong key refused, a new certificate served without a restart).

**The very first start.** The proxy needs a certificate to start, and Let's
Encrypt needs the proxy running to answer its challenge. So, once:

```bash
infra/production/deploy.sh certificate temporary   # a 7-day self-signed one (the watch alerts about it at once)
infra/production/deploy.sh deploy <release>        # the site runs, with the temporary certificate
infra/production/deploy.sh certificate issue       # option A below; or install option B's files
```

## Option A: Let's Encrypt, HTTP challenge (no Cloudflare)

**Founder** (F-17): the domain, and the address Let's Encrypt writes to.
Then, as root on the server:

1. Install certbot from the distribution (`apt-get install certbot`).
2. In `/etc/markx/compose.env`: `MARKX_TLS_RENEWAL=certbot` and
   `MARKX_ACME_EMAIL=<the founder's address>`.
3. `infra/production/deploy.sh certificate issue`: certbot answers the
   challenge from `MARKX_ACME_DIR` (the proxy already serves
   `/.well-known/acme-challenge/` on port 80) and its **deploy hook** is
   `deploy.sh certificate install-renewed`, which installs the certificate
   as above. Certbot remembers the hook for every renewal.
4. `infra/production/deploy.sh certificate install-timer`: a systemd timer
   (`infra/production/systemd/`) runs `deploy.sh certificate renew` twice a
   day at a random minute; certbot renews only a certificate within 30
   days of expiry, and the same command then checks the result. A missed
   run happens at the next boot. (Certbot's own packaged timer, if
   enabled, uses the same remembered hook; both together are harmless.)

**Tested** in the rehearsal with a stand-in for certbot that contacts
nobody: `renew` calls certbot with the challenge folder, certbot's deploy
hook installs the renewed certificate and the proxy serves it; the timer's
units are written with the server's paths and `systemd-analyze verify`
accepts them. **Real world:** a real certificate authority, a real domain.

## Option B: Cloudflare in front, an origin certificate

Cloudflare's dashboard issues an origin certificate (valid for years) for
the hostname; save its two files in a folder and run `deploy.sh certificate
install <folder>`. Leave `MARKX_TLS_RENEWAL=none`. Set Cloudflare's TLS mode
to "Full (strict)", enable `snippets/cloudflare-real-ip.conf` (its
`.example` explains it) and restrict the server's firewall to Cloudflare's
ranges. Install the timer too (step 4 above): with renewal off it still
runs the check every day.

## Checks

- `infra/production/deploy.sh certificate check`: days left; exit 1 inside
  the warning time or once expired. Also in the pre-deployment checklist.
- The watch's alert `tls.certificate_expiring` (or
  `tls.certificate_unreadable`): on the admin operations page (`/admin/ops`), in the
  Telegram group, or in the log.
- From outside: an SSL Labs test shows TLS 1.2 and 1.3 only, a complete
  chain, and HSTS.
