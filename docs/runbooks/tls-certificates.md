# The site's certificate

**No domain and no certificate exist yet.** The proxy is ready for either
of the two usual ways; which one is the founder's choice with the domain
(and with Cloudflare, blueprint M.2: Proposed).

The proxy reads, read-only, from `MARKX_TLS_DIR` (default `/etc/markx/tls`):

| File | Owner and mode | What |
| --- | --- | --- |
| `fullchain.pem` | root, 644 | the certificate and its chain |
| `privkey.pem` | uid 101 (the proxy's user), 400 | the private key; nobody else may read it |

`deploy.sh check` refuses anything else. After replacing either file:
`docker compose ... exec proxy nginx -s reload` (no restart needed).

## Option A: Let's Encrypt, HTTP challenge (no Cloudflare)

The proxy already serves `/.well-known/acme-challenge/` on port 80 from
`MARKX_ACME_DIR` (default `/var/lib/markx/acme`). With certbot installed on
the host:

```bash
certbot certonly --webroot -w /var/lib/markx/acme -d <hostname> \
  --deploy-hook /opt/markx/infra/production/install-certificate.sh
```

where the deploy hook (to be written with the founder's chosen tool; not in
the repository yet) copies `$RENEWED_LINEAGE/fullchain.pem` and
`privkey.pem` into `/etc/markx/tls` with the owners above and reloads the
proxy. Certbot renews on its own timer. The very first certificate needs
the proxy running, which needs a certificate: start with a self-signed one
for the hostname (as `rehearse.sh` does), then replace it.

## Option B: Cloudflare in front, an origin certificate

Cloudflare's dashboard issues an origin certificate (valid for years) for
the hostname; install its two files as above, set Cloudflare's TLS mode to
"Full (strict)", enable `snippets/cloudflare-real-ip.conf` (its `.example`
explains it) and restrict the server's firewall to Cloudflare's ranges.

## Checks

- Expiry: `openssl x509 -enddate -noout -in /etc/markx/tls/fullchain.pem`
  (in the pre-deployment checklist; an outside monitor should also warn 14
  days before, once one exists).
- From outside: an SSL Labs test shows TLS 1.2 and 1.3 only, a complete
  chain, and HSTS.
