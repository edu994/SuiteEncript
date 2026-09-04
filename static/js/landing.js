/* Landing cinematográfica: scroll-reveal + parallax sutil en las capturas,
   todo con IntersectionObserver + CSS vanilla — sin librería de animación
   externa (mismo criterio que ya sacó Three.js del proyecto: no sumar
   otro origen al CSP). Respeta prefers-reduced-motion: el parallax ni
   siquiera se activa si el usuario lo tiene configurado así en el SO. */

const reduceMotion = window.matchMedia("(prefers-reduced-motion: reduce)").matches;

// Nav fija: sombra + fondo más sólido una vez que se empieza a scrollear.
const nav = document.getElementById("cinematicNav");
const progress = document.getElementById("scrollProgress");

function onScrollChrome() {
    if (nav) nav.classList.toggle("se-nav-scrolled", window.scrollY > 40);
    if (progress) {
        const doc = document.documentElement;
        const pct = (doc.scrollTop / (doc.scrollHeight - doc.clientHeight)) * 100;
        progress.style.width = pct + "%";
    }
}
window.addEventListener("scroll", onScrollChrome, { passive: true });
onScrollChrome();

// Revela cada elemento marcado con .se-reveal cuando entra en pantalla.
const revealObserver = new IntersectionObserver(
    (entries) => {
        entries.forEach((entry) => {
            if (entry.isIntersecting) {
                entry.target.classList.add("se-in-view");
                revealObserver.unobserve(entry.target);
            }
        });
    },
    // Antes threshold:0.3 (un elemento no empezaba a revelarse hasta estar
    // 30% dentro de la pantalla) -- eso dejaba un tramo en blanco entre el
    // final de una escena y la aparición de la siguiente, sensación de
    // "corte" entre página y página en vez de scroll continuo. rootMargin
    // negativo en el borde inferior hace que el
    // observer considere "visible" un elemento un poco antes de que entre
    // físicamente en pantalla, así el fade-in ya está en marcha cuando
    // llega a la vista.
    { threshold: 0.01, rootMargin: "0px 0px -15% 0px" }
);
document.querySelectorAll(".se-reveal").forEach((el) => revealObserver.observe(el));

// Parallax sutil: la captura se mueve un poco más lento que el scroll
// dentro de su propia escena, para dar sensación de profundidad.
if (!reduceMotion) {
    const frames = document.querySelectorAll(".se-media-frame img");
    function applyParallax() {
        frames.forEach((img) => {
            const rect = img.getBoundingClientRect();
            const center = rect.top + rect.height / 2 - window.innerHeight / 2;
            img.style.transform = `translateY(${center * -0.06}px)`;
        });
    }
    window.addEventListener("scroll", () => requestAnimationFrame(applyParallax), { passive: true });
    applyParallax();
}

// Fondo del hero: red de nodos conectados dibujada en <canvas>, en vez de
// un video real de la app -- se busca algo con temática de ciberseguridad,
// no una grabación de pantalla. Vanilla JS + Canvas 2D, sin librerías,
// mismo criterio que el resto de este archivo, y evita el problema real
// que tenía la versión con video (grabarlo, recortarlo, mantenerlo
// sincronizado con el diseño cada vez que este cambia).
(function initHeroNetwork() {
    const canvas = document.getElementById("heroNetwork");
    if (!canvas) return;
    const ctx = canvas.getContext("2d");

    function hexToRgb(hex) {
        const m = hex.trim().replace("#", "");
        return [parseInt(m.slice(0, 2), 16), parseInt(m.slice(2, 4), 16), parseInt(m.slice(4, 6), 16)];
    }
    const accent = getComputedStyle(document.documentElement).getPropertyValue("--se-accent") || "#5b8def";
    const [cr, cg, cb] = hexToRgb(accent);

    const LINK_DIST = 150;
    // 0.4 se leía como demasiado lento/estático para un fondo animado --
    // subido hasta que el movimiento se nota sin robarle atención al texto.
    const DRIFT_SPEED = 0.85;
    let width = 0;
    let height = 0;
    let nodes = [];

    function seedNodes() {
        // Densidad fija por área en vez de un número fijo de nodos: se ve
        // igual de tenue en un hero angosto de mobile que en un monitor
        // ancho, sin quedar vacío ni saturado en ningún tamaño. El tope de
        // 70 tenía sentido cuando el canvas vivía dentro del hero limitado
        // a 1100px -- ahora que cubre la ventana completa (ver el fix de
        // .se-page), esa misma cantidad de nodos quedaba mucho más
        // dispersa en pantallas anchas, uno de los motivos de "se ve muy
        // poco". Subido el tope y bajado el divisor para más densidad.
        const count = Math.min(160, Math.max(28, Math.round((width * height) / 13000)));
        nodes = Array.from({ length: count }, () => ({
            x: Math.random() * width,
            y: Math.random() * height,
            vx: (Math.random() - 0.5) * DRIFT_SPEED,
            vy: (Math.random() - 0.5) * DRIFT_SPEED,
            r: 1.2 + Math.random() * 1.6,
            pulse: 0,
        }));
    }

    function resize() {
        // El canvas ahora es position:fixed a la ventana (no al hero), así
        // que se dimensiona contra el viewport, no contra su elemento padre.
        const dpr = Math.min(window.devicePixelRatio || 1, 2);
        width = window.innerWidth;
        height = window.innerHeight;
        canvas.width = width * dpr;
        canvas.height = height * dpr;
        canvas.style.width = width + "px";
        canvas.style.height = height + "px";
        ctx.setTransform(dpr, 0, 0, dpr, 0, 0);
        seedNodes();
    }

    function drawFrame(animate) {
        ctx.clearRect(0, 0, width, height);

        if (animate) {
            nodes.forEach((n) => {
                n.x += n.vx;
                n.y += n.vy;
                if (n.x < 0 || n.x > width) n.vx *= -1;
                if (n.y < 0 || n.y > height) n.vy *= -1;
                if (n.pulse > 0) n.pulse = Math.max(0, n.pulse - 0.02);
            });
            if (Math.random() < 0.012) {
                nodes[Math.floor(Math.random() * nodes.length)].pulse = 1;
            }
        }

        for (let i = 0; i < nodes.length; i++) {
            for (let j = i + 1; j < nodes.length; j++) {
                const a = nodes[i];
                const b = nodes[j];
                const dx = a.x - b.x;
                const dy = a.y - b.y;
                const dist = Math.sqrt(dx * dx + dy * dy);
                if (dist < LINK_DIST) {
                    // Tercera pasada: 0.4 seguía leyéndose como "opaco".
                    ctx.strokeStyle = `rgba(${cr}, ${cg}, ${cb}, ${(1 - dist / LINK_DIST) * 0.6})`;
                    ctx.lineWidth = 1;
                    ctx.beginPath();
                    ctx.moveTo(a.x, a.y);
                    ctx.lineTo(b.x, b.y);
                    ctx.stroke();
                }
            }
        }

        nodes.forEach((n) => {
            ctx.beginPath();
            ctx.arc(n.x, n.y, n.r + n.pulse * 2, 0, Math.PI * 2);
            ctx.fillStyle = `rgba(${cr}, ${cg}, ${cb}, ${0.85 + n.pulse * 0.15})`;
            ctx.fill();
        });
    }

    resize();
    window.addEventListener("resize", resize, { passive: true });

    if (reduceMotion) {
        drawFrame(false);
        return;
    }

    // El canvas es un fondo fijo para todo el recorrido del scroll, no
    // solo el hero -- así que solo se pausa cuando de verdad no tiene
    // sentido seguir dibujando: la pestaña en segundo plano. No depende de
    // si el hero está a la vista.
    let rafId = null;
    function loop() {
        drawFrame(true);
        rafId = requestAnimationFrame(loop);
    }
    function sync() {
        const shouldRun = !document.hidden;
        if (shouldRun && rafId === null) loop();
        if (!shouldRun && rafId !== null) {
            cancelAnimationFrame(rafId);
            rafId = null;
        }
    }

    sync();
    document.addEventListener("visibilitychange", sync);
})();

// Flechas de navegación manual del carrusel de noticias. La cinta corre
// sola con una animación CSS (@keyframes se-marquee, ver landing.css) que
// se pausa sola al pasar el cursor -- eso ya funcionaba. Lo que faltaba
// era poder avanzar/retroceder a mano para buscar una noticia puntual sin
// esperar a que el auto-scroll la traiga. No se puede mezclar la animación
// CSS con un transform controlado por JS (la animación sigue "dueña" de la
// propiedad aunque esté en pausa), así que al primer click se congela la
// posición actual, se apaga la animación (clase .se-news-track-manual) y
// de ahí en más el transform lo maneja este script.
(function initNewsNav() {
    const marquee = document.querySelector(".se-news-marquee");
    if (!marquee) return;
    const track = marquee.querySelector(".se-news-track");
    const prevBtn = marquee.querySelector("[data-se-news-prev]");
    const nextBtn = marquee.querySelector("[data-se-news-next]");
    const firstSet = track ? track.querySelector(".se-news-track-set") : null;
    if (!track || !prevBtn || !nextBtn || !firstSet) return;

    let offset = 0;
    let manual = false;

    function currentTranslateX() {
        const transform = getComputedStyle(track).transform;
        if (transform === "none") return 0;
        const match = transform.match(/matrix\(([^)]+)\)/);
        if (!match) return 0;
        const parts = match[1].split(",").map(Number);
        return parts[4] || 0;
    }

    function enableManual() {
        if (manual) return;
        offset = currentTranslateX();
        track.classList.add("se-news-track-manual");
        // El difuminado angosto de los bordes (ver .se-news-viewport en
        // landing.css, sobre todo en mobile: 38%/62%) está pensado para la
        // cinta en movimiento continuo -- ahí ninguna tarjeta "descansa"
        // el tiempo suficiente para notarlo. En modo manual la cinta se
        // queda quieta en cada paso, y esa misma zona angosta hace que la
        // tarjeta activa se vea desvanecida de los dos lados en vez de
        // completa. marquee.classList aplica el estado
        // "manual" para que el CSS pueda relajar el mask-image solo ahí.
        marquee.classList.add("se-news-marquee-manual");
        track.style.transform = `translateX(${offset}px)`;
        manual = true;
    }

    function step(direction) {
        enableManual();
        const card = track.querySelector(".se-news-card");
        if (!card) return;
        const style = getComputedStyle(card);
        const cardStep = card.offsetWidth + parseFloat(style.marginLeft) + parseFloat(style.marginRight);
        const setWidth = firstSet.scrollWidth;

        offset -= direction * cardStep;
        // El contenido está duplicado una vez (mismo truco que la
        // animación automática) -- al pasar de un extremo, se salta al
        // punto equivalente del otro set, así se puede seguir avanzando o
        // retrocediendo sin tope, como con el auto-scroll.
        if (offset <= -setWidth) offset += setWidth;
        if (offset > 0) offset -= setWidth;

        track.style.transform = `translateX(${offset}px)`;
    }

    prevBtn.addEventListener("click", () => step(-1));
    nextBtn.addEventListener("click", () => step(1));
})();
