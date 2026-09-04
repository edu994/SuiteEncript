// Service worker de SuiteEncript (Fase 11, PWA).
//
// Decisión de seguridad deliberada: esto es un gestor de contraseñas y una
// bóveda de archivos, no un blog. Un service worker mal diseñado en una app
// así puede convertirse en un problema real — si cacheara HTML de páginas
// autenticadas (dashboard, lista de contraseñas, bóveda), esas respuestas
// quedarían en el Cache Storage del navegador, legibles desde las DevTools
// o por cualquiera con acceso al dispositivo, incluso después de un logout.
//
// Por eso el alcance de este service worker es intencionalmente angosto:
// SOLO intercepta y cachea archivos estáticos bajo /static/ (CSS, JS,
// íconos, el manifest). Cualquier otra petición — cualquier página HTML,
// cualquier ruta con datos de usuario — pasa de largo sin que este archivo
// la toque en absoluto. No hay "modo offline" del dashboard ni de la
// bóveda a propósito: no es una app que deba funcionar sin conexión, y
// pretender que sí lo hace agregaría superficie de riesgo sin un beneficio
// real para este proyecto.

const CACHE_NAME = "suiteencript-static-v1";
const STATIC_ASSETS = [
    "/static/css/style.css",
    "/static/js/main.js",
    "/static/manifest.json",
    "/static/icons/icon-192.png",
    "/static/icons/icon-512.png",
];

self.addEventListener("install", (event) => {
    event.waitUntil(
        caches.open(CACHE_NAME).then((cache) => cache.addAll(STATIC_ASSETS))
    );
    self.skipWaiting();
});

self.addEventListener("activate", (event) => {
    event.waitUntil(
        caches.keys().then((keys) =>
            Promise.all(
                keys
                    .filter((key) => key !== CACHE_NAME)
                    .map((key) => caches.delete(key))
            )
        )
    );
    self.clients.claim();
});

self.addEventListener("fetch", (event) => {
    const url = new URL(event.request.url);

    const isCacheableStaticAsset =
        event.request.method === "GET" &&
        url.origin === self.location.origin &&
        url.pathname.startsWith("/static/");

    if (!isCacheableStaticAsset) {
        // No interviene: deja que el navegador maneje la petición como si
        // este service worker no existiera. Esto incluye deliberadamente
        // toda página HTML y cualquier ruta con datos de usuario.
        return;
    }

    // Red primero, caché solo como respaldo si no hay conexión -- no al
    // revés. Un cache-first hace que, una vez que un archivo estático queda
    // cacheado, el navegador lo siga sirviendo para siempre sin importar
    // que cambie en el servidor (así se detectó este bug: un cambio real
    // en landing.js/landing.css no se veía ni haciendo refresh normal,
    // porque el service worker nunca volvía a pedirle el archivo a la
    // red). Coherente con el criterio de arriba: esta app no necesita
    // velocidad offline para sus estáticos, necesita no mostrar contenido
    // desactualizado.
    event.respondWith(
        fetch(event.request)
            .then((response) => {
                if (response.ok) {
                    const responseClone = response.clone();
                    caches.open(CACHE_NAME).then((cache) => {
                        cache.put(event.request, responseClone);
                    });
                }
                return response;
            })
            .catch(() => caches.match(event.request))
    );
});
