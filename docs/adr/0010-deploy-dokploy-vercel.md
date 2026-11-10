# Deploy the backend on a VPS with Dokploy and the storefront on Vercel

The backend (Django, Celery, PostgreSQL, Redis) is deployed on a VPS managed with Dokploy, to keep hosting costs low and predictable. The storefront is deployed on Vercel for its Next.js support and preview deployments.

Amended by ADR-0026: the Quetzal staff console is deployed with Dokploy on the VPS, not on Vercel. The storefront on Vercel needs the Pro plan, because the Hobby plan forbids commercial use.
