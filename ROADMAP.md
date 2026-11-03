# Roadmap — commerce-platform

Plataforma de comercio multi-tienda (`anime` y `home`) con un solo backend en Django + DRF,
tiendas web en Next.js, app móvil en React Native y una plataforma de agentes
(publicación en Instagram, ventas por WhatsApp, seguimiento y paquetes sugeridos).

Este documento define **qué se entrega en cada fase** y **cuándo algo cuenta como terminado**.
Los prompts para OpenCode de cada fase están en `phase-prompts.md`.

---

## 1. Ciclo de vida de una tarea

```
backlog → ready → in progress → in review → done
```

| Estado | Significa |
|---|---|
| `backlog` | La idea existe, pero todavía no se puede empezar. |
| `ready` | Cumple la **Definition of Ready**: cualquiera (tú o un agente) puede tomarla sin preguntar. |
| `in progress` | Alguien la está construyendo, con el test que falla escrito primero. |
| `in review` | Hay un PR abierto, el CI corre y pasa por `/code-review`. |
| `done` | Cumple **toda** la Definition of Done que le aplica. |

Una tarea que se cumple a medias **no** es `done`: se divide y lo pendiente vuelve a `backlog`.

---

## 2. Definition of Ready (para pasar a `ready`)

- [ ] Tiene un objetivo de una frase: qué cambia para el negocio o para el usuario.
- [ ] Tiene criterios de aceptación verificables (se puede escribir un test para cada uno).
- [ ] Está en una sola capa o módulo, o dice explícitamente qué módulos toca.
- [ ] Sus dependencias están en `done` (modelos, endpoints, credenciales, accesos externos).
- [ ] Usa el vocabulario de `GLOSSARY.md`; si introduce un término nuevo, la tarea lo agrega.
- [ ] Cabe en un PR revisable (si no, se parte con `/to-tickets`).

---

## 3. Definition of Done

### 3.1 Base: aplica a TODAS las tareas

**Código**
- [ ] Todo en inglés: nombres, comentarios, mensajes de commit y de error.
- [ ] Respeta la regla de dependencias: `domain` no importa Django, DRF ni `infrastructure`.
- [ ] Ningún módulo escribe en los modelos de otro; se comunica por servicios o puertos.
- [ ] Sin secretos en el código, en los tests ni en el historial de git.

**Pruebas**
- [ ] El test que demuestra el criterio de aceptación existe y se escribió antes que el código.
- [ ] Casos de uso: test unitario con puertos falsos, sin base de datos.
- [ ] Endpoints: test de API de punta a punta.
- [ ] `pytest` y `ruff` pasan en local y en el CI.

**Base de datos**
- [ ] La migración se revisó a mano y se puede revertir.
- [ ] Cambios de datos (roles, permisos) van en migraciones de datos, no a mano. Las tiendas se crean
      con el comando `create_store`, nunca en una migración.

**API**
- [ ] El esquema OpenAPI está actualizado y `packages/api-client` regenerado si cambió la API.
- [ ] Los errores de dominio nuevos están mapeados a un código HTTP en el exception handler.

**Revisión y entrega**
- [ ] PR con descripción (`/pr`), revisado con `/code-review` y sin comentarios abiertos.
- [ ] Mezclado en `main`.
- [ ] Desde la fase 6: desplegado en **staging** y verificado a mano (smoke test).
- [ ] Documentación al día: `AGENTS.md`, `GLOSSARY.md`, ADR si se tomó una decisión de arquitectura.

### 3.2 Extra si la tarea toca datos de una tienda
- [ ] Toda consulta filtra por `request.store`.
- [ ] Hay un test que prueba que los datos de una tienda **no** aparecen en la otra.

### 3.3 Extra si la tarea ejecuta una acción importante
(cambiar precios, mover stock, reembolsar, aprobar o publicar contenido, escribirle a un cliente)
- [ ] La autorización está **dentro del caso de uso** con el puerto `Authorizer`, no solo en la vista.
- [ ] Hay un test con un usuario sin el permiso, que falla con 403.
- [ ] La acción queda registrada (quién, cuándo, sobre qué).

### 3.4 Extra si la tarea integra un servicio externo
(Mercado Pago, TikTok Shop, Meta, WhatsApp, LLMs)
- [ ] El servicio está detrás de un puerto, con una implementación falsa para los tests.
- [ ] Los webhooks verifican la firma y responden rápido (encolan y contestan 200).
- [ ] Es **idempotente**: recibir el mismo evento dos veces no duplica nada.
- [ ] Tiene reintentos con espera y un estado de error visible (no falla en silencio).
- [ ] Las credenciales son por tienda, cifradas en la base con una llave que vive fuera de ella, y se
      leen solo por el puerto `CredentialStore` (ADR-0020).

### 3.5 Extra si la tarea crea o cambia un agente o un prompt
- [ ] El prompt es una plantilla versionada y se subió la versión (`PROMPT_VERSION`).
- [ ] El dataset de evaluación del agente tiene casos para lo que se cambió, incluidos casos de borde.
- [ ] El eval pasa el umbral del agente y la puntuación quedó registrada para comparar.
- [ ] Cada llamada al LLM queda en `AgentRun` (modelo, versión, tokens, latencia, resultado).
- [ ] El agente solo usa las herramientas permitidas en su `AgentDefinition`.
- [ ] Datos de negocio (precios, stock, descuentos) salen de herramientas, nunca del texto del modelo,
      y el validador en código lo comprueba.
- [ ] Si habla con clientes: el traspaso a humano está probado y el agente calla después del traspaso.

### 3.6 Extra si la tarea es de frontend (web o app)
- [ ] Funciona en celular primero (la mayoría llega desde TikTok, Instagram y WhatsApp).
- [ ] Lint, chequeo de tipos y build pasan; preview de Vercel revisado.
- [ ] Páginas públicas de producto y categoría renderizadas en servidor, con metadata para SEO.

---

## 4. Definition of Done de una fase

- [ ] Todas sus tareas están en `done`.
- [ ] Se cumple su **criterio de salida** (abajo), demostrado de punta a punta.
- [ ] `/retro` hecho y sus mejoras aplicadas a `AGENTS.md`, skills o este roadmap.
- [ ] Tag de versión en git (`v0.<fase>.0`; las fases con letra usan `v0.<fase>.1`, por ejemplo `v0.4.1` para 4b).

---

## 5. Fases

### Fase 0 — Planeación
**Objetivo:** que las decisiones grandes estén escritas antes de escribir código.
**Entregables:**
- `AGENTS.md` en la raíz.
- `GLOSSARY.md` con el vocabulario del dominio (en inglés).
- ADRs de las decisiones tomadas: monolito modular, clean architecture en módulos con reglas,
  DRF como capa fina, RBAC por tienda, Dokploy, plataforma de agentes común.
- OpenCode configurado con DeepSeek y permisos; skills de Matt Pocock instaladas en el repo con `npx skills` y `/setup-matt-pocock-skills` ejecutado.
- Tickets de la fase 1 en el gestor de issues.
**Criterio de salida:** `/wayfinder` no deja decisiones abiertas que bloqueen las fases 1 a 3.

### Fase 1 — Esqueleto
**Objetivo:** un proyecto que arranca igual en cualquier máquina.
**Entregables:** monorepo con `.gitignore` y README; `docker-compose.yml` con PostgreSQL y Redis;
Django con configuración por `.env` y dependencias con `uv` (`pyproject.toml` y `uv.lock`);
modelo `User` propio con login por email.
**Criterio de salida:** entras a `/admin/` con tu email y existe el primer commit.

### Fase 2 — Base de la API
**Objetivo:** la base sobre la que se construye todo endpoint.
**Entregables:** DRF con JWT, `/api/v1/`, paginación y filtros; exception handler de dominio con
respuestas RFC 9457; OpenAPI en `/api/v1/docs/`; endpoint de salud; middleware de `X-Store`
(endpoints globales por defecto, los de tienda lo declaran); pytest, ruff, pre-commit;
GitHub Actions corriendo pruebas en cada PR.
**Criterio de salida:** la documentación abre y el CI está en verde en un PR.

### Fase 3 — Tiendas y RBAC
**Objetivo:** que cada persona solo pueda hacer lo que su rol le permite en cada tienda.
**Entregables:** `Store` y el comando `create_store` (con él se crean `anime` y `home`);
`StoreFeatureFlag` por tienda; `Permission`, `Role`, `StoreMembership`;
roles iniciales (`owner`, `store_admin`, `content_editor`, `warehouse`, `support`);
permisos que usarán las fases siguientes; puerto `Authorizer` y su implementación; `IsStoreStaff`.
**Criterio de salida:** un usuario con rol en una tienda no puede actuar en la otra, probado con tests.

### Fase 4 — Catálogo
**Objetivo:** cargar y mostrar los productos reales.
**Entregables:** proveedores, diseños, categorías planas con esquema de atributos y opciones,
productos, variantes con SKU generado, colecciones y media en Cloudflare R2; admin con inlines;
comandos `import_catalog` y `set_prices`; endpoints públicos de lectura, incluida la búsqueda por SKU.
**Criterio de salida:** el catálogo real está cargado con `import_catalog` y la API lo devuelve solo
para `home` (las imágenes llegan en la fase 4b).

### Fase 4b — Fotos del catálogo
**Objetivo:** que el staff convierta una foto del celular en la imagen del catálogo.
**Entregables:** endpoints de staff para media del catálogo con `catalog.manage`; página para
celular donde se sube la foto (HEIC a JPEG) y se marcan las cuatro esquinas; procesamiento en
Celery que endereza, recorta a la proporción real y corrige la luz.
**Criterio de salida:** un miembro del staff fotografía una frazada y queda como su imagen principal.

### Fase 5 — Inventario y pedidos
**Objetivo:** vender sin vender de más.
**Entregables:** módulos `inventory` y `orders` con clean architecture; `ReserveStock`, `PlaceOrder`,
`CancelOrder`; historial de movimientos; copia de datos en cada `OrderItem`; skill propia
`new-domain-module`.
**Criterio de salida:** un pedido descuenta stock en una sola transacción y pedir de más de una variante
que se vende desde stock devuelve 409 (vender sin stock una variante sobre pedido se decide en el
/grill-with-docs de la fase 5).

### Fase 5b — Compras y resurtido
**Objetivo:** comprarle al proveedor en el ciclo semanal sin perder lo que se vendió sin stock.
**Entregables:** lista de compras, órdenes de compra con recepciones parciales que crean
movimientos de entrada, calendario de resurtido con días cerrados y visitas extra, corte de pedidos
y fecha prometida en la zona horaria de la tienda, borrador automático de la orden de compra.
**Criterio de salida:** una venta sin stock entra a la lista de compras, pasa a una orden de compra
y una recepción parcial suma al stock lo recibido.

### Fase 6 — Pagos y despliegue
**Objetivo:** cobrar de verdad y tener la plataforma en internet.
**Entregables:** módulo `payments` con Mercado Pago (tarjeta y OXXO) y webhook idempotente;
Celery con email de confirmación; Dockerfile; VPS con Dokploy; staging y producción con bases y
credenciales separadas; respaldos a almacenamiento externo; logs y seguimiento de errores.
**Criterio de salida:** un pago de prueba en staging marca el pedido como pagado y envía el email.
**Trámites que arrancan aquí:** revisión de la app de Meta (Instagram) y verificación de
WhatsApp Business Platform.

### Fase 6b — Envíos
**Objetivo:** cotizar y enviar con Envíosperros todo pedido que no sea de TikTok Shop.
**Entregables:** puerto `ShippingProvider` con Envíosperros (cotización, guía, descarga y
recolección); el canal decide la paquetería; recargo por envío al dejar el paquete en sucursal,
configurable por tienda (hoy 10 MXN para `home`); peso y medidas de paquete obligatorios para cotizar.
**Criterio de salida:** un pedido en staging se cotiza, se genera y descarga su guía, y el precio
mostrado incluye el recargo.

### Fase 7 — Storefront, primero con la tienda de frazadas
**Objetivo:** vender en tu propio dominio.
**Entregables:** `packages/api-client` generado; un solo `storefront` en Next.js con tema por tienda, resuelta por dominio, que
sale en vivo con `home`: catálogo, producto, carrito, checkout, confirmación e historial; SEO; despliegue en Vercel con previews.
**Criterio de salida:** alguien compra una frazada en tu dominio.

### Fase 8 — Tienda de anime y canales
**Objetivo:** vender en todos los canales sin descuadrar el stock.
**Entregables:** `anime` en el mismo storefront (su dominio y su tema, sin app nueva); sincronización de pedidos y stock con TikTok Shop; feeds de catálogo
para Meta y TikTok; eventos de conversión desde el servidor; UTM guardados en el pedido.
**Criterio de salida:** una venta en TikTok Shop aparece como pedido y descuenta stock.

### Fase 9 — Plataforma de agentes y publicación en Instagram
**Objetivo:** un solo runtime de agentes, con el primer agente en producción.
**Entregables:**
- Runtime común: puerto `LLMClient` (Claude y DeepSeek), registro de herramientas,
  `AgentDefinition` (handle, prompt, versión, modelo, herramientas permitidas), `AgentRun`.
- Colas separadas: `realtime`, `agents_batch`, `default`.
- Módulo `social` y agente `@social`: calendario, generador, validador, aprobación y publicación.
- Menciones desde Ghosty Teams: agentes webhook que llegan a `/api/v1/ops/agents/invoke/`,
  con verificación de origen, permisos del usuario y tope de relevos entre agentes.
- `evals/` con dataset y graders por agente, corriendo en el CI cuando cambian los prompts.
**Criterio de salida:** una publicación se genera, pasa la validación, la apruebas desde Teams y
aparece en Instagram.

### Fase 10 — Ventas por WhatsApp
**Objetivo:** atender y cerrar ventas por WhatsApp sin perder clientes por esperar.
**Entregables:**
- Módulo `conversations`: `Customer`, consentimientos, `Conversation`, `Message`, traspaso a humano.
- Adaptador de WhatsApp: webhook con firma, envío de mensajes, plantillas aprobadas.
- Agente `@ventas`: busca productos, consulta stock, arma el carrito, genera link de pago,
  traspasa a humano; un turno a la vez por conversación con agrupación de mensajes en ráfaga.
- Bandeja de conversaciones en traspaso (admin y aviso en Teams).
- `Order.conversation_id` y métricas de costo por conversación y tasa de traspaso.
**Criterio de salida:** un cliente pregunta por WhatsApp, recibe información correcta, paga con el
link y el pedido aparece como venta de esa conversación.

### Fase 11 — Seguimiento a clientes
**Objetivo:** recuperar ventas que se quedaron a medias, sin molestar.
**Entregables:** reglas en código (sin respuesta, carrito abandonado, postventa); agente
`@seguimiento` que redacta sobre plantillas; límite de frecuencia por cliente; baja inmediata ante
"no me escribas"; relevo a `@ventas` cuando el cliente responde con intención de compra.
**Criterio de salida:** un carrito abandonado recibe un seguimiento con plantilla y, si el cliente
responde, la conversación pasa a ventas.

### Fase 12 — Paquetes sugeridos
**Objetivo:** subir el ticket promedio con combinaciones que ya se venden juntas.
**Entregables:** análisis de canasta sobre `OrderItem` (pares frecuentes, margen, stock);
agente `@paquetes` que nombra y describe; `Bundle` y `BundleItem` como borrador con aprobación;
venta de paquetes en las tiendas web.
**Criterio de salida:** la sugerencia semanal genera un paquete, lo apruebas y se puede comprar.
**Requisito:** al menos unos meses de historial de ventas.

### Fase 13 — Observabilidad y endurecimiento
**Objetivo:** ver qué hace el sistema y hacerlo difícil de romper.
**Entregables:** OpenTelemetry para Django, Celery y LLMs; dashboards (peticiones, errores,
pedidos por tienda, tokens y costo por agente y versión de prompt); límites de peticiones;
revisión de seguridad; prueba de restauración de respaldos.
**Criterio de salida:** los dashboards muestran tráfico real y se restauró un respaldo en staging.

### Fase 14 — App móvil
**Objetivo:** que el cliente escanee un producto y lo guarde.
**Entregables:** app en Expo; escaneo de QR con enlaces universales; favoritos sincronizados con
la web; login con JWT; publicación con EAS Build y actualizaciones con EAS Update.
**Criterio de salida:** escaneas la etiqueta de un producto y se abre en la app con su precio actual.

---

## 6. Trabajo en paralelo (fuera de las fases)

| Qué | Cuándo |
|---|---|
| Vender frazadas en TikTok Shop | Ya: la temporada de frío no espera a la plataforma |
| Campañas con `@ads` en Ghosty Teams | Ya, si las vas a usar |
| Revisión de la app de Meta para publicar en Instagram | Desde la fase 6 |
| Verificación de WhatsApp Business Platform y plantillas | Desde la fase 6 |
| Acceso a la API de TikTok Shop | Desde la fase 6 |