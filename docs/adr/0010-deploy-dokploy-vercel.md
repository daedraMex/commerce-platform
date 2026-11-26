# Deploy the backend on a VPS with Dokploy and the storefront on Vercel

The backend (Django, Celery, PostgreSQL, Redis) is deployed on a VPS managed with Dokploy, to keep hosting costs low and predictable. The storefront is deployed on Vercel for its Next.js support and preview deployments.

Amended by ADR-0026: the Quetzal staff console is deployed with Dokploy on the VPS, not on Vercel. The storefront on Vercel needs the Pro plan, because the Hobby plan forbids commercial use.

## Amendment (2026-11-26)

The backend runs on a Hostinger VPS KVM 2 (2 vCPU, 8 GB RAM, 100 GB NVMe, US
region) managed with Dokploy, and the DNS zone is on Cloudflare. Dokploy's
Traefik is the single HTTPS entry and gets Let's Encrypt certificates per host;
there is no second proxy. Dokploy remains the deployment tool, not a hosting
control panel; the VPS runs Ubuntu 24.04 with official Docker Engine and Compose
installed by Dokploy.

This does not change Vercel: Quetzal is not on Vercel (ADR-0026), and the one
storefront stays on Vercel from Phase 7 (Pro plan, since Hobby forbids commercial
use). Phase 6a deploys only the backend and Quetzal; the storefront's Vercel
project and preview settings remain a Phase 7 decision.
