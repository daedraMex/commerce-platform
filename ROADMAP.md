# Roadmap — commerce-platform

Plataforma de comercio multi-tienda (`anime`: mercancía de anime como gorras, playeras y
otros productos de anime; `kawaii`: papelería kawaii como portatarjetas de BTS, lomo cards,
libretas, stickers y plumas, además de squishies, mercancía de K-pop, snacks y frazadas; `llaveros`: llaveros de todo tipo, menudeo y mayoreo
para revendedores; y `home`: frazadas) con un solo backend en Django + DRF, tiendas web en
Next.js, app móvil en Kotlin Multiplatform y una plataforma de agentes (publicación en Instagram,
ventas por WhatsApp, seguimiento y paquetes sugeridos).

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
- [ ] Desde la fase 6a: desplegado en **staging** y verificado a mano (smoke test).
- [ ] Documentación al día: `AGENTS.md`, `GLOSSARY.md`, ADR si se tomó una decisión de arquitectura.

### 3.2 Extra si la tarea toca datos de una tienda
- [ ] Toda consulta filtra por `request.store`.
- [ ] Hay un test que prueba que los datos de una tienda **no** aparecen en otra tienda.

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

Las fases están numeradas por tema, no por orden: un número no dice cuándo va una fase.
El orden de trabajo es este:

1. **4b**, fotos del catálogo.
2. **6a**, despliegue: se separa de la fase 6 y se adelanta, para que el staff cargue
   productos y fotos directo en producción.
3. **4c**, alta y edición de productos en Quetzal.
4. Cuatro carriles en paralelo:
   - **Backend:** 5 → 6 → 6b.
   - **Tienda física:** 5c, en cuanto exista la 5.
   - **Video:** 4d.
   - **Storefront:** 7, primero todo lo que solo lee el catálogo.
5. **7** abre cada tienda al público cuando están la 6b y la 4d, y cuando esa tienda tiene su
   catálogo y sus fotos.
6. **8**, canales.
7. **5b**, compras y resurtido.

Reglas del orden:
- Ninguna fase quita ni recorta funciones de otra para llegar antes.
- Las fases no tienen fechas.
- Cada arista de bloqueo entre carriles se escribe en el ticket como una línea
  `Blocked by: #n` (o como dependencia nativa de GitHub). La fábrica no empieza un ticket con un
  bloqueo abierto ni apila ramas.
- Un contrato que comparten dos carriles (por ejemplo, el de pedidos y checkout entre la 5, la 6
  y el carrito de la 7) se escribe primero en `docs/contracts/` (ADR-0031), y su implementación
  va después.
- Hasta la fase 5b solo se vende lo que hay en stock: una variante agotada se muestra como
  agotada y no se puede comprar.

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
**Entregables:** `Store` y el comando `create_store` (con él se crean `anime`, `kawaii`, `llaveros` y `home`);
`StoreFeatureFlag` por tienda; `Permission`, `Role`, `StoreMembership`;
roles iniciales (`owner`, `store_admin`, `content_editor`, `warehouse`, `support`);
permisos que usarán las fases siguientes; puerto `Authorizer` y su implementación; `IsStoreStaff`.
**Criterio de salida:** un usuario con rol en una tienda no puede actuar en otra tienda, probado con tests.

### Fase 4 — Catálogo
**Objetivo:** cargar y mostrar los productos reales.
**Entregables:** proveedores, diseños, categorías planas con esquema de atributos y opciones,
productos, variantes con SKU generado, colecciones y media en Cloudflare R2; admin con inlines;
comandos `import_catalog` y `set_prices`; endpoints públicos de lectura, incluida la búsqueda por SKU.
**Criterio de salida:** el catálogo real está cargado con `import_catalog` y la API lo devuelve solo
para `home` (las imágenes llegan en la fase 4b).

### Fase 4b — Fotos del catálogo
**Objetivo:** que el staff convierta una o varias fotos del celular en imágenes del catálogo,
individuales o grupales.
**Entregables:** módulo `photos` con clean architecture y endpoints de staff con `catalog.manage`;
original privado y preview autorizado; página para celular en Quetzal, la consola de staff
(ADR-0026), con inicio de sesión BFF (ADR-0027), tienda en la URL y menú por permisos; subida
multipart con HEIC a JPEG, orientación EXIF aplicada y metadata eliminada; foto individual con
cuatro esquinas y recorte rectificado; productos de contorno con marco de recorte rectangular;
foto grupal 4:5 enlazada a varios productos; procesamiento en Celery que endereza, recorta a la
proporción de la talla fotografiada y corrige la luz de forma determinista (sin eliminación de fondo
con ML); renditions 320/800 WebP con claves derivadas; idempotencia por tienda y creador;
`ProductMedia.is_active`; `packages/api-client` generado con orval; `GET /api/v1/me/`;
`Store.accent_color`.
**Prerrequisito (PR humano):** `web/console/scripts/check.sh` y la fábrica corriendo el check de cada
parte que toca un ticket; el job E2E de nivel 2 en GitHub Actions.
**Criterio de salida:** un miembro del staff fotografía una frazada, la aprueba y queda en el carrusel
del producto (la primera imagen es la portada), y una foto grupal aprobada queda enlazada a varios productos. El video es la fase 4d.

### Fase 6a — Despliegue
**Va justo después de la 4b.** Se separó de la fase 6 para que el staff deje de cargar productos y
fotos en una base local y lo haga directo en producción.
**Objetivo:** tener la plataforma en internet: la API, el worker, el beat y Quetzal.
**Entregables:** Dockerfile; VPS con Dokploy; `docker-compose.prod.yml` con api, worker y `beat`
(la misma imagen con distintos comandos; sin `beat` no corre el barrido de fotos atoradas de la
4b), PostgreSQL y Redis; staging y producción con bases, buckets de R2 y credenciales separadas;
Quetzal en internet con HTTPS (la cámara y el escáner del navegador solo funcionan en un contexto
seguro); el subdominio `q.berlekgroup.com` apunta a la plataforma, que redirige cada link de
etiqueta (ADR-0035); respaldos a almacenamiento externo; logs y seguimiento de errores;
`manage.py check --deploy` en CI con una configuración de producción; `docs/deployment.md`.
**Carga inicial, una sola vez:** producción empieza limpia. El catálogo de cada tienda entra con
`import_catalog` desde las hojas del operador, y un comando de verificación compara lo importado
contra la hoja (tiendas, categorías, productos, variantes y SKU) y reporta lo que no cuadra. Las
fotos de prueba de la base local no se migran: las fotos se toman en producción. Las hojas de stock
`sku,cantidad` no se importan aquí, sino en la fase 5.
**Criterio de salida:** un miembro del staff entra a Quetzal en producción desde su celular,
el catálogo importado cuadra con sus hojas, y una foto tomada ahí queda en el carrusel del producto.

### Fase 4c — Alta y edición de productos en Quetzal
**Va justo después de la 6a.** Hoy los productos solo entran con `import_catalog`; esta fase deja
darlos de alta y corregirlos desde el celular, en el negocio.
**Objetivo:** que el staff dé de alta un producto con sus variantes y su foto desde el celular,
sin pasar por una hoja.
**Entregables:** endpoints de staff con `catalog.manage` para crear y editar productos y variantes;
página para celular en Quetzal: tienda, categoría, nombre, atributos y las opciones que define la
categoría para armar las variantes, cada una con su SKU generado; al guardar, lleva directo al
flujo de fotos de la 4b para cada variante. **Se puede editar:** nombre, descripción, atributos,
precio de cada variante, agregar variantes, y desactivar una variante o un producto. **No se puede
editar:** el SKU (va impreso en las etiquetas y nunca cambia una vez creado), la tienda del
producto ni su categoría (un producto en la categoría equivocada se desactiva y se da de alta otra
vez). Las variantes nunca se borran: se desactivan.
**Criterio de salida:** desde el celular, un miembro del staff da de alta un producto de dos
variantes, le toma foto a cada una, corrige su precio, y el producto sale en la API pública con
sus dos SKU.

### Fase 4d — Video del catálogo
**Va en paralelo después de la 4c**, en su propio carril. El video sale con el storefront: la fase 7
no abre ninguna tienda al público sin él, y el ticket de la 7 que muestra el video en la página de
producto lleva `Blocked by:` el ticket de la 4d que publica su URL.
**Objetivo:** que el staff agregue un video corto del producto sin cambiar los llamadores de la fase 4b.
**Entregables:** subida directa a R2 con URLs prefirmadas detrás del puerto `MediaUploader` (el camino
que ADR-0028 difirió); validación de duración, códec y tamaño; renditions de video, reproducción en
Quetzal y URL pública en la API del producto. Sin campos de video en la fase 4b; el diseño se decide
en el /grill-with-docs de esta fase.
**Criterio de salida:** un video corto subido desde Quetzal se reproduce en Quetzal, y la API
pública del producto devuelve su URL; el storefront lo muestra en la fase 7.

### Fase 5 — Inventario y pedidos
**Objetivo:** vender sin vender de más.
**Va primero en el carril de backend.** Su primer ticket escribe el contrato de pedidos y checkout
en `docs/contracts/` (ADR-0031): la fase 6 y el carrito de la fase 7 dependen de él y pueden
empezar en cuanto esté escrito, sin esperar al resto de la fase.
**Entregables:** módulos `inventory` y `orders` con clean architecture; `ReserveStock`, `PlaceOrder`,
`CancelOrder`; historial de movimientos; copia de datos en cada `OrderItem`; skill propia
`new-domain-module`. Los squishies se venden en caja cerrada y en pieza suelta, como variantes
distintas con su propio SKU y su propio stock; un movimiento de "abrir caja" convierte una caja
cerrada en N piezas sueltas (salida de 1 caja y entrada de N piezas en una sola operación
registrada con su motivo), para que el stock nunca se descuadre.
**Precios por volumen y canales:** cada variante puede tener precios por volumen (por ejemplo,
1, 6 y 12 piezas) con un margen mínimo por pieza que se valida contra el costo y la comisión de
cada canal. El mayoreo se vende sobre todo por canales directos (el agente de ventas de WhatsApp
de la fase 10); el menudeo, por TikTok Shop y el storefront.
**Paquetes:** la venta de paquetes es parte de esta fase; el staff los crea a mano con `Bundle`
y `BundleItem`, porque los llaveros por docena y el kit de inicio son productos desde el primer
día y no necesitan historial de ventas. Hay dos tipos. El paquete fijo siempre lleva los mismos
componentes (el kit de inicio para revendedores y los sets de squishies). El paquete surtido
lleva N piezas de un conjunto (las variantes de un producto o una colección) con reglas
opcionales como un máximo por variante; se puede vender cuando el conjunto tiene stock
suficiente bajo esas reglas. Al tomar el pedido el sistema elige la mezcla empezando por la
variante con más stock, reserva y descuenta cada variante elegida, y el pedido lista las piezas
exactas que hay que empacar (por ejemplo, 4 Tanjiro, 5 Nezuko y 3 Zenitsu). Una docena surtida
de llaveros de Demon Slayer o 12 llaveros de Spider-Man mezclando los colores azul y rojo son
paquetes surtidos.
**Canal de venta:** cada pedido guarda su canal: tienda en línea, local, TikTok Shop, marketplace o
WhatsApp.
**Stock inicial:** hasta esta fase el stock vive en una hoja `sku,cantidad` por tienda. La fase 5
importa cada hoja una sola vez como stock inicial de la ubicación de su tienda, reporta los SKU que
no encuentra, y después las hojas se retiran.
**Sin vender lo que no hay:** hasta la fase 5b solo se vende lo que hay en stock. Vender sobre
pedido una variante sin stock llega con la 5b, que es la que la convierte en una compra al proveedor.
**Criterio de salida:** un pedido descuenta stock en una sola transacción, pedir de más de una
variante devuelve 409, y la hoja de stock de una tienda queda importada como su stock inicial.

### Fase 5c — Tienda física
**Va en paralelo a la 6 y la 6b**, en cuanto existe la fase 5.
**Objetivo:** vender en el local y llevar el stock con el mismo sistema que la tienda en línea.
**Entregables:**
- Venta en el local en Quetzal: se escanea el QR de la etiqueta de producto con un escáner USB
  (Quetzal saca el SKU del link de la etiqueta y también acepta el SKU solo) y cada pieza se
  suma a la cuenta, como en la caja del súper; Quetzal muestra el total, el staff escribe con
  cuánto pagó el cliente y Quetzal calcula el cambio. Al cobrar se registra un pedido con canal
  local y pago en efectivo (solo efectivo; Quetzal no conecta ninguna terminal), se descuenta el
  stock y se imprime el ticket.
- Ticket de venta en la impresora térmica de tickets (OFICHIDO, rollo de 58 mm) con la tienda, la
  fecha, los productos, el total, lo que pagó el cliente y el cambio. Se imprime con el diálogo
  de impresión del navegador; antes de construir la venta se imprime un ticket de prueba para
  confirmar el ancho del rollo y que se lea bien.
- Conteo de stock: se escanea con el escáner USB o con la cámara del celular en el navegador y
  se registra el conteo como un movimiento de ajuste con su motivo.
- Consulta de precio y stock: se escanea un SKU y Quetzal muestra su precio y su stock.
- Etiquetas de producto desde Quetzal, en la impresora de etiquetas (Zendio Z-474, 203 dpi):
  el staff elige productos y cantidades, o sube una hoja `sku,cantidad`, y sale una etiqueta por
  pieza con el QR del link de etiqueta, nombre, variante y precio, en etiqueta de 2×1" y de llavero
  de 63×22 mm. Reemplaza el script que se usa hoy para el inventario inicial.
- Al final de la fase, un endpoint de ventas del día por canal para los tableros.
**Criterio de salida:** una venta en el local descuenta stock, queda como pedido con canal local e
imprime su ticket, y una etiqueta impresa desde Quetzal se escanea y encuentra su variante.

### Fase 5b — Compras y resurtido
**Va después de la fase 8.** Con ella llega vender sobre pedido una variante sin stock.
**Objetivo:** comprarle al proveedor en el ciclo semanal sin perder lo que se vendió sin stock.
**Entregables:** lista de compras, órdenes de compra con recepciones parciales que crean
movimientos de entrada, calendario de resurtido con días cerrados y visitas extra, corte de pedidos
y fecha prometida en la zona horaria de la tienda, borrador automático de la orden de compra.
**Proveedor "Por definir":** cada tienda tiene un proveedor de relleno llamado "Por definir" para
los diseños cuyo proveedor todavía no se conoce. La fase 5b tiene que manejar esos diseños; cómo,
se decide en su /grill-with-docs.
**Criterio de salida:** una venta sin stock entra a la lista de compras, pasa a una orden de compra
y una recepción parcial suma al stock lo recibido.

### Fase 6 — Pagos
**Objetivo:** cobrar de verdad en línea.
**Va en el carril de backend, después de la 5.** Puede empezar en cuanto la fase 5 escribe el
contrato de pedidos y checkout. El despliegue que antes era parte de esta fase es ahora la fase 6a.
**Entregables:** módulo `payments` con clean architecture: puerto `PaymentGateway` con Mercado Pago
(tarjeta y OXXO) y webhook idempotente; Celery con email de confirmación. El dominio usa nuestros
términos; un pago guarda el id de Mercado Pago solo como referencia externa, con el nombre del
proveedor (ADR-0034). Qué proveedor de pagos usa una tienda es un ajuste por tienda: hoy las cuatro
tiendas usan la misma cuenta de Mercado Pago, guardada como credencial de cada tienda (ADR-0020).
**Criterio de salida:** un pago de prueba en staging marca el pedido como pagado y envía el email.
**Trámites que arrancan aquí:** revisión de la app de Meta (Instagram) y verificación de
WhatsApp Business Platform.

### Fase 6b — Envíos
**Objetivo:** cotizar y enviar con Envíosperros todo pedido que no sea de TikTok Shop.
**Entregables:** módulo `shipping` con clean architecture, como `payments`; puerto
`ShippingProvider` con Envíosperros (cotización, guía, descarga y recolección); el canal decide la
paquetería; recargo por envío al dejar el paquete en sucursal, configurable por tienda (hoy 10 MXN
para `home`); peso y medidas de paquete obligatorios para cotizar. El dominio usa nuestros términos
(cotización, envío, paquetería, guía) y nunca identificadores ni formatos de Envíosperros: el
adaptador los traduce, y un envío guarda el id del proveedor solo como referencia externa, con el
nombre del proveedor (ADR-0034). Qué proveedor de envíos usa una tienda es un ajuste por tienda, así
que reemplazar a Envíosperros es agregar un adaptador detrás de `ShippingProvider`, sin cambiar
pedidos ni checkout. Hoy las cuatro tiendas usan la misma cuenta de Envíosperros, guardada como
credencial de cada tienda (ADR-0020). La guía de 4×6" se imprime desde Quetzal en la misma
impresora de etiquetas de la 5c, con el rollo de 4×6".
**Criterio de salida:** un pedido en staging se cotiza, se genera y descarga su guía, y el precio
mostrado incluye el recargo.

### Fase 7 — Storefront y las cuatro tiendas
**Objetivo:** vender en tu propio dominio con las cuatro tiendas: `home`, `kawaii`, `llaveros` y
`anime`.
**Va en su propio carril desde la 4c.** Todo lo que solo lee el catálogo (catálogo, producto,
búsqueda, colecciones y el tema de cada tienda) empieza ya, con la API pública del catálogo y el
`packages/api-client` que existen desde la 4b. El carrito, el checkout y la confirmación llevan
`Blocked by:` el contrato de pedidos y checkout de la fase 5 y la fase 6. El video de la página de
producto lleva `Blocked by:` la 4d.
**Entregables:** un solo `storefront` en Next.js con tema por tienda, resuelta por dominio:
catálogo, producto (con el video público que la API devuelve desde la fase 4d), carrito, checkout,
confirmación e historial; SEO; zoom solo en imágenes de al menos 1,200 px de ancho (ADR-0033);
despliegue en Vercel (plan Pro) con previews. Usa el `packages/api-client` y la sesión con BFF
(ADR-0027) que ya existen desde la 4b; el tema completo por tienda se decide en su
/grill-with-docs. Cada tienda tiene su dominio y su tema, sin app nueva.
**Link de etiqueta:** el QR de la etiqueta de producto ya lleva un link fijo,
`https://q.berlekgroup.com/<tienda>/<SKU>` (ADR-0035), que la plataforma redirige a la página del
producto. La URL pública de la página la decide esta fase y puede cambiar después, porque las
etiquetas no la codifican: solo cambia la redirección. No hay etiqueta de anaquel.
**Cada tienda abre cuando está lista:** el storefront se construye para las cuatro, y cada tienda
abre al público en cuanto tiene su catálogo cargado, sus fotos y las funciones de la fase 5 que
necesitan sus productos; las demás no la esperan. Solo `home` tiene imágenes del proveedor
(ADR-0033): `kawaii`, `llaveros` y `anime` necesitan fotos propias de cada variante. `kawaii`
necesita "abrir caja" para los squishies; `llaveros` necesita los paquetes surtidos para las
docenas.
**Líneas de producto:** las tiendas se dividen por público en cuatro: `anime` (mercancía de
anime: gorras, playeras y otros productos de anime), `kawaii` (papelería kawaii: portatarjetas
de BTS, lomo cards, libretas, stickers y plumas; squishies, mercancía de K-pop, snacks y
frazadas), `llaveros` (llaveros de todo tipo: kawaii, anime, superhéroes y animales; menudeo y
mayoreo para revendedores) y `home` (frazadas). Los llaveros van a `llaveros`, no a `kawaii`. Las
bolsas y mochilas van a `anime` o `kawaii` según su diseño. Una línea solo se vuelve tienda nueva
cuando tiene otro comprador. Las tiendas son datos (`create_store`) y las categorías también
(ADR-0024).
**Una frazada en dos tiendas:** el mismo diseño de frazada se vende en `home` y en `kawaii` como
dos productos con stock separado; se compra stock para cada tienda.
**Datos del catálogo:** las categorías de `kawaii`, `llaveros` y `anime` las crea como datos un
script fuera del repositorio. Color, tamaño de papel, piezas, presentación (caja cerrada o pieza
suelta) y talla de ropa son opciones, así que cada combinación es una variante con su propio SKU y
su propio stock; todo lo demás es un atributo. Los diseños usan sus proveedores reales (Beka,
Altos, Adeko, Arcade Store, …) o el proveedor de relleno "Por definir" de su tienda cuando el
proveedor no se conoce.
**Segmentación y catálogo de llaveros:** las campañas dentro de `llaveros` se segmentan con
colecciones (`Kawaii`, `Anime`, `Superheroes`, `Animals`, `Wholesale/Starter kit`), no con más
tiendas. Un llavero podrá listarse más adelante también en `kawaii` o `anime` como un producto
separado con su propio stock asignado; se empieza sin eso. Los productos nunca se mueven entre
tiendas, así que cada línea se coloca en su tienda final desde el inicio. La categoría de
llaveros es datos, no código: un producto por serie (por ejemplo, "Llavero Demon Slayer"), con
una opción obligatoria "Personaje" (una variante por personaje o pose, cada una con su propio
SKU, stock y foto) y una opción "Color" opcional solo cuando un personaje viene en varios
colores (por ejemplo, Spider-Man azul y rojo). Nunca se usa "Color" para decir el personaje:
rompe los filtros del storefront, los feeds de catálogo y el texto que escriben los agentes.
Tamaño y material son atributos de la categoría, iguales para todas las variantes.
**Criterio de salida:** cada una de las cuatro tiendas está abierta en su dominio y alguien compró
en ella.

### Fase 8 — Canales
**Objetivo:** vender en todos los canales sin descuadrar el stock.
**Entregables:** cada tienda con sus propias cuentas de redes sociales y de TikTok Shop, guardadas
como credenciales de integración por tienda (ADR-0020); sincronización de pedidos y stock con
TikTok Shop; feeds de catálogo para Meta y TikTok; eventos de conversión desde el servidor; UTM
guardados en el pedido. Las tiendas abren en la fase 7; esta fase solo agrega los canales.
**Criterio de salida:** una venta en TikTok Shop aparece como pedido y descuenta stock.

### Fase 9 — Plataforma de agentes y publicación en Instagram
**Objetivo:** un solo runtime de agentes, con el primer agente en producción.
**Entregables:**
- Runtime común: puerto `LLMClient` (Claude y DeepSeek), registro de herramientas,
  `AgentDefinition` (handle, prompt, versión, modelo, herramientas permitidas), `AgentRun`.
- Colas separadas: `realtime`, `agents_batch`, `default`.
- Módulo `social` y agente `@social`: calendario, generador, validador, aprobación y publicación.
- Los agentes también recomiendan paquetes de productos y escriben guiones de grabación
  (tomas, duración, gancho, texto en pantalla) al estilo de los videos de referencia; el
  staff graba los videos y los sube por Quetzal (fase 4d). Nada de video generado por IA.
  La venta de paquetes fijos y surtidos ya existe desde la fase 5 (`Bundle` y `BundleItem`);
  aquí los agentes solo los recomiendan. La lógica de recomendación se comparte con la fase 12
  y se diseña una sola vez.
- Las recomendaciones aprenden a nivel de serie, colección y categoría, no por SKU, para
  seguir siendo válidas cuando cambian los modelos; una variante nueva hereda el historial de
  su serie (arranque en frío).
- Las recomendaciones solo usan lo que hay en stock ahora; las variantes inactivas o sin stock
  nunca se proponen.
- Los personajes nuevos se cargan como variantes del producto de su serie, así que los
  paquetes surtidos (definidos por un conjunto) los incluyen solos y dejan caer los agotados
  sin editar el paquete.
- El agente marca los paquetes fijos cuyos componentes están agotados o inactivos para que el
  staff los actualice.
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
**Objetivo:** subir el ticket promedio recomendando combinaciones que ya se venden juntas.
**Entregables:** análisis de canasta sobre `OrderItem` (pares frecuentes, margen, stock);
agente `@paquetes` que nombra y describe y propone borradores sobre los `Bundle` y `BundleItem`
que ya existen desde la fase 5, para aprobación. Esta fase solo recomienda paquetes; la venta
de paquetes fijos y surtidos es de la fase 5. La lógica de recomendación se comparte con la
fase 9 (guiones de video) y se diseña una sola vez. Ejemplos de recomendación: una docena
surtida de llaveros o 12 llaveros de Spider-Man mezclando los colores azul y rojo.
**Reglas de recomendación:** aprenden a nivel de serie, colección y categoría, no por SKU, para
seguir siendo válidas cuando cambian los modelos; una variante nueva hereda el historial de su
serie (arranque en frío). Solo usan lo que hay en stock ahora; las variantes inactivas o sin
stock nunca se proponen. Los personajes nuevos se cargan como variantes del producto de su
serie, así que los paquetes surtidos (definidos por un conjunto) los incluyen solos y dejan
caer los agotados sin editar el paquete. El agente marca los paquetes fijos cuyos componentes
están agotados o inactivos para que el staff los actualice.
**Criterio de salida:** la sugerencia semanal propone un paquete, lo apruebas y se puede vender
con el flujo de la fase 5.
**Requisito:** al menos unos meses de historial de ventas.

### Fase 13 — Observabilidad y endurecimiento
**Objetivo:** ver qué hace el sistema y hacerlo difícil de romper.
**Entregables:** OpenTelemetry para Django, Celery y LLMs; dashboards (peticiones, errores,
pedidos por tienda, tokens y costo por agente y versión de prompt); límites de peticiones;
revisión de seguridad; prueba de restauración de respaldos.
**Criterio de salida:** los dashboards muestran tráfico real y se restauró un respaldo en staging.

### Fase 14 — App móvil
**Objetivo:** que el cliente escanee un producto y lo guarde.
**Entregables:** app en Kotlin Multiplatform con Compose Multiplatform y Material 3 (Android e
iOS, ADR-0029), con el tema de cada tienda generado desde su `accent_color`; cliente Kotlin generado
desde el esquema OpenAPI; escaneo de QR: la etiqueta de producto lleva el link de etiqueta
(ADR-0035), que abre el producto en la app con enlaces universales, o en la web si no está
instalada; favoritos sincronizados con la web; login con JWT; publicación en Google Play y App Store.
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
| Catálogo de `kawaii`, `llaveros` y `anime` con el script de categorías y las hojas de cada tienda | Ya; entra a producción en la fase 6a |
| Fotos de producto con el celular, guardadas por tienda | Ya; se suben desde Quetzal cuando exista la fase 6a |
| Stock en una hoja `sku,cantidad` por tienda | Hasta la fase 5, que la importa como stock inicial |
| Etiquetas de producto con el script fuera de la plataforma, ya con el link de etiqueta (ADR-0035) | Hasta la fase 5c, que las imprime desde Quetzal |
| Redirección temporal de `q.berlekgroup.com` desde el hosting de `berlekgroup.com` a TikTok Shop o WhatsApp | Desde que se imprime la primera etiqueta con link hasta la fase 6a |
| Pantalla de tinta electrónica (TRMNL BYOS) con las ventas del día por canal | Después de la fase 5c, que publica el endpoint |
| Segunda impresora de etiquetas solo para guías de envío | Cuando haya tantos envíos al día que cambiar de rollo estorbe |
