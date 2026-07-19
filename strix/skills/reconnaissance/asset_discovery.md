---
name: asset-discovery
description: Passive asset and attack-surface discovery via certificate transparency, TLS SAN pivoting, passive DNS, and ASN/IP enumeration to find hosts beyond subdomain brute force.
---

# Asset Discovery

Most engagements start from a small seed (one domain, one org name) but the real attack surface is far larger: forgotten hosts, staging/internal-named services, acquisitions, and infrastructure that never appears in a subdomain wordlist. This skill covers building a broad, deduplicated inventory of an org's internet-facing assets using **passive** sources — certificate transparency, TLS certificate metadata, passive DNS, and ASN/IP-range data — then collapsing it into a probed attack surface. The goal is coverage and pivoting, not exploitation of any single service.

Stay in scope: only enumerate and probe assets you are authorized to test. Passive sources can surface hosts owned by third parties, acquisitions, or unrelated tenants that share infrastructure — confirm ownership before treating a host as in-scope.

## Attack Surface

- Hosts discoverable only via issued certificates (CT logs) but not via DNS brute force
- Internal/staging/pre-prod hostnames leaked in certificate SAN lists
- Sibling and acquisition domains sharing certificates, ASNs, or IP ranges with the seed
- Wildcard and short-lived certs revealing naming conventions (`*.internal.example.com`, `k8s-*`, `argocd.*`)
- IP ranges (ASN-owned) hosting services with no DNS name at all
- Virtual hosts co-located on shared IPs (multiple apps behind one address)
- Non-HTTP services on discovered hosts (databases, message queues, admin ports)

## Reconnaissance Pipeline

Work outward from each seed and feed every new name/IP back into the earlier stages until it stops growing:

1. **Seed** - domains, org/legal names, known IPs, email domains, code-host org (GitHub/GitLab org).
2. **Certificate transparency** - pull all logged certs for the seed domains and org name.
3. **TLS SAN/CN extraction** - parse every cert's Subject CN and `subjectAltName` list; each new name is a new seed.
4. **Passive DNS** - resolve names to IPs and IPs back to names (reverse); harvest historical records.
5. **ASN / IP ranges** - map owned IPs to their ASN, expand to the org's netblocks, sweep for live hosts.
6. **Active TLS pivot** - connect to live IPs/ports, read the presented cert, extract SANs (catches internal hosts never sent to public CT).
7. **Consolidate & probe** - dedupe into a host inventory, then probe with `httpx` for status/title/tech/server.

### Certificate Transparency (CT)

CT logs record nearly every publicly-trusted certificate issued. Query by domain (returns certs whose SAN/CN match) and by organization.

- **crt.sh** (free, no key):
  - JSON by domain incl. subdomains: `https://crt.sh/?q=%25.example.com&output=json`
  - By organization name: `https://crt.sh/?O=Example+Inc&output=json`
  - Extract unique names from `name_value` (newline-separated SANs) and `common_name`.
  - Example: `curl -s 'https://crt.sh/?q=%25.example.com&output=json' | jq -r '.[].name_value' | tr '\n' '\n' | sed 's/\*\.//' | sort -u`
- **Censys / Shodan** (API key; richer pivoting): search certs by `parsed.names`, `parsed.subject.organization`, or a specific cert fingerprint, then pivot to hosts serving that cert. Use when you have keys configured; do not assume availability.
- **Other CT front-ends / APIs**: `certspotter`, `google CT`, `entrust`, projectdiscovery `chaos`. Cross-check because no single index is complete.
- **Wildcards and naming conventions**: a `*.corp.example.com` or `*.eks.example.com` SAN reveals an internal naming scheme even if individual hosts resolve privately — use it to seed targeted `httpx`/`subfinder` runs and DNS guesses (`grafana.corp`, `ci.corp`, `vault.corp`).

### TLS Certificate SAN/CN Pivoting

Certificates are one of the strongest cross-asset links.

- **SAN expansion**: one cert often lists many hostnames (marketing + api + admin + internal). Extract every SAN, not just the queried name.
- **Shared-cert pivot**: the same cert (same fingerprint) served on multiple IPs/hosts ties disparate assets to one owner. Search Censys/Shodan by cert `fingerprint_sha256`.
- **Issuer/org pivot**: certs with the same `subject.organization` or `organizationalUnit` frequently belong to the same target; pivot on it to find sibling domains.
- **Active read**: for live hosts, read the served cert directly to catch names never submitted to public CT:
  - `echo | openssl s_client -connect HOST:443 -servername HOST 2>/dev/null | openssl x509 -noout -text | grep -A1 'Subject Alternative Name'`
  - Or `httpx -l hosts.txt -tls-grab -json` to capture cert SANs at scale.
- **Internal leak signal**: SANs like `localhost`, `*.internal`, `*.svc.cluster.local`, `*.local`, or RFC1918-style hostnames on a public cert reveal internal naming and sometimes internal services fronted publicly.

### Passive DNS & Resolution

- Forward-resolve every discovered name (A/AAAA/CNAME); keep CNAME chains — they reveal third-party providers and CDNs.
- **Reverse DNS (PTR)** on discovered IPs to surface co-located hostnames.
- **Historical/passive DNS** (SecurityTrails, VirusTotal, projectdiscovery, passivedns providers) for names that no longer resolve but may still front live infra.
- Combine with `subfinder` (passive source aggregation) as one input among many — CT + passive DNS + subfinder together beat any single source.

### ASN & IP-Range Discovery

- Map a known IP to its **ASN and netblock**: `whois -h whois.cymru.com " -v <IP>"`, or BGP/ASN lookup services.
- If the org runs its own ASN, enumerate all announced prefixes and treat those ranges as candidate scope (confirm ownership — cloud/shared ASNs are not org-owned).
- For cloud-hosted targets, the IP belongs to the provider, not the org — pivot via cert/vhost rather than netblock.
- Sweep candidate ranges cheaply with `naabu` (top ports) then `httpx` to find services with no DNS name.

## Consolidation & Probing

Turn the raw name/IP set into a usable attack surface:

1. **Dedupe** names and IPs into a single inventory; note source(s) per asset for confidence.
2. **Live probe** with `httpx`: `httpx -l hosts.txt -sc -title -server -td -tls-grab -json -o assets.jsonl` — capture status, title, server, detected tech, and cert SANs in one pass (each grabbed SAN feeds back into step 3 of the pipeline).
3. **Classify** assets by role from title/tech/path signals: app, API, marketing, auth, CI/CD, observability, storage, admin, VCS, mail. Do not hardcode to any single product — cluster by function.
4. **Port sweep** interesting hosts with `naabu` for non-HTTP services (DBs, caches, brokers, mgmt ports).
5. **Prioritize** by exposure and value: unauthenticated management/observability/admin UIs, dev/staging environments, anything on an internal naming convention, and hosts serving certs with internal SANs.

Discovery ends here — hand specific findings to the appropriate specialist skill:
- Exposed dashboards / debug / observability / metadata leaks → `information_disclosure`
- Login/admin panels with default or weak creds → `weak_password_detection`
- Dangling DNS / unclaimed provider resources found during resolution → `subdomain_takeover`
- Cloud-provider consoles/metadata surfaces → `aws` / `gcp` / `kubernetes`

## Validation & Scope Hygiene

- **Confirm ownership** before flagging a discovered host as in-scope: matching cert org, shared netblock, or DNS under a seed domain are strong signals; a shared cloud IP or CDN CNAME is not.
- **Deduplicate aggressively**: the same service appears under many names (vhost aliases, CDN edges); collapse to distinct origins to avoid inflating the surface.
- **Record provenance**: keep which source produced each asset — it drives confidence and reproducibility.
- **Passive first**: prefer CT/passive DNS/whois (no target traffic) before any active probing, and keep active probing rate-limited and in-scope.

## False Positives

- CDN/edge hostnames and provider default names that are not org-owned
- Shared-hosting neighbors on the same IP (vhost co-tenancy, not the target's asset)
- Stale historical DNS entries pointing at reassigned infrastructure
- Wildcard-cert-implied hostnames that never actually resolve or serve content

## Pro Tips

1. Loop the pipeline — every SAN, PTR, and CNAME target is a new seed until the set stops growing.
2. crt.sh is the cheapest high-yield source (no key); Censys/Shodan add cert-fingerprint and vhost pivoting when keys are available.
3. Active TLS SAN reads catch internal hostnames that never hit public CT — always cert-grab live hosts.
4. Internal-looking SANs (`*.internal`, `*.svc.cluster.local`, staging names) are the highest-signal leads for finding forgotten/misconfigured services.
5. Wildcard SANs reveal naming conventions — use them to seed targeted guesses rather than blind brute force.
6. Cluster by function, not by product name, so the workflow generalizes to any exposed service, not a specific vendor.

## Summary

Broad passive discovery — CT + TLS SAN pivoting + passive DNS + ASN/IP mapping, looped until convergence — finds the assets brute force misses, especially internal-named and forgotten services leaked through certificates. Build the inventory, probe and classify it generically, then route each interesting asset to the specialist skill for that class.
