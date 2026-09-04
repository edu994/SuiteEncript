function seCopyToClipboard(elementId, message) {
    const el = document.getElementById(elementId);
    if (!el || !el.value) return;
    navigator.clipboard.writeText(el.value);
    if (message) alert(message);
}

document.addEventListener('DOMContentLoaded', function () {
    document.querySelectorAll('[data-se-range-display]').forEach(function (range) {
        const target = document.getElementById(range.dataset.seRangeDisplay);
        if (!target) return;
        target.textContent = range.value;
        range.addEventListener('input', function () { target.textContent = range.value; });
    });

    document.querySelectorAll('[data-se-copy]').forEach(function (btn) {
        btn.addEventListener('click', function () {
            seCopyToClipboard(btn.dataset.seCopy, btn.dataset.seCopyMessage);
        });
    });

    document.querySelectorAll('[data-se-copy-text]').forEach(function (btn) {
        btn.addEventListener('click', function () {
            navigator.clipboard.writeText(btn.dataset.seCopyText);
            if (btn.dataset.seCopyMessage) alert(btn.dataset.seCopyMessage);
        });
    });

    // "Ojo" de contraseña: revela el texto solo mientras se mantiene el
    // puntero encima (ratón) o pulsado (táctil/teclado) — no es un
    // interruptor que se queda fijo al soltar.
    document.querySelectorAll('[data-se-peek-password]').forEach(function (btn) {
        const input = document.getElementById(btn.dataset.sePeekPassword);
        if (!input) return;
        const show = () => { input.type = 'text'; };
        const hide = () => { input.type = 'password'; };

        btn.addEventListener('mouseenter', show);
        btn.addEventListener('mouseleave', hide);
        btn.addEventListener('touchstart', show, { passive: true });
        btn.addEventListener('touchend', hide);
        btn.addEventListener('touchcancel', hide);
        btn.addEventListener('keydown', function (e) {
            if (e.key === 'Enter' || e.key === ' ') { e.preventDefault(); show(); }
        });
        btn.addEventListener('keyup', function (e) {
            if (e.key === 'Enter' || e.key === ' ') hide();
        });
        // Es un botón dentro de un <form>; sin esto, Enter/Espacio lo
        // activarían como submit en vez de solo revelar la contraseña.
        btn.addEventListener('click', function (e) { e.preventDefault(); });
    });

    // Menú de cuenta del navbar (avatar + nombre -> Panel/Mi cuenta/
    // Auditoría/Salir). Un único menú a la vez: abrir uno cierra los demás.
    var dropdownToggles = document.querySelectorAll('[data-se-dropdown-toggle]');
    function closeAllDropdowns(except) {
        dropdownToggles.forEach(function (toggle) {
            if (toggle === except) return;
            var menu = document.getElementById(toggle.getAttribute('aria-controls'));
            toggle.setAttribute('aria-expanded', 'false');
            if (menu) menu.hidden = true;
        });
    }
    dropdownToggles.forEach(function (toggle) {
        var menu = document.getElementById(toggle.getAttribute('aria-controls'));
        if (!menu) return;
        toggle.addEventListener('click', function (e) {
            e.stopPropagation();
            var isOpen = toggle.getAttribute('aria-expanded') === 'true';
            closeAllDropdowns();
            toggle.setAttribute('aria-expanded', String(!isOpen));
            menu.hidden = isOpen;
        });
    });
    document.addEventListener('click', function () { closeAllDropdowns(); });
    document.addEventListener('keydown', function (e) {
        if (e.key !== 'Escape') return;
        var openToggle = document.querySelector('[data-se-dropdown-toggle][aria-expanded="true"]');
        closeAllDropdowns();
        if (openToggle) openToggle.focus();
    });

    // Reveal en scroll (mismo mecanismo que static/js/landing.js, promovido
    // acá para el resto de la app): agrega .se-in-view la primera vez que
    // el elemento entra en pantalla, después deja de observarlo.
    var revealTargets = document.querySelectorAll('[data-se-reveal]');
    if (revealTargets.length && 'IntersectionObserver' in window) {
        var revealObserver = new IntersectionObserver(function (entries) {
            entries.forEach(function (entry) {
                if (!entry.isIntersecting) return;
                entry.target.classList.add('se-in-view');
                revealObserver.unobserve(entry.target);
            });
        }, { threshold: 0.01, rootMargin: '0px 0px -10% 0px' });
        revealTargets.forEach(function (el) { revealObserver.observe(el); });
    } else {
        // Sin soporte de IntersectionObserver (o sin elementos): mostrar
        // directo, nunca dejar contenido invisible por falta de JS.
        revealTargets.forEach(function (el) { el.classList.add('se-in-view'); });
    }

    // Resplandor que sigue al puntero en las tarjetas interactivas (ver
    // .se-card-interactive::before en style.css). Se omite por completo con
    // prefers-reduced-motion -- no es información, es puro adorno.
    if (!window.matchMedia('(prefers-reduced-motion: reduce)').matches) {
        document.querySelectorAll('.se-card-interactive').forEach(function (card) {
            card.addEventListener('mousemove', function (e) {
                var rect = card.getBoundingClientRect();
                card.style.setProperty('--se-mx', ((e.clientX - rect.left) / rect.width * 100) + '%');
                card.style.setProperty('--se-my', ((e.clientY - rect.top) / rect.height * 100) + '%');
            });
        });
    }
});

// PWA (Fase 11): registra el service worker desde la raíz ("/service-worker.js",
// servido por una ruta propia en main.py, no bajo /static/) para que su alcance
// cubra toda la app y no solo /static/ — necesario para que el navegador la
// considere instalable. El service worker en sí solo cachea estáticos (ver su
// propio archivo para el porqué), así que registrarlo no cambia el
// comportamiento de ninguna página con datos de usuario.
if ('serviceWorker' in navigator) {
    window.addEventListener('load', function () {
        navigator.serviceWorker.register('/service-worker.js').catch(function () {
            // Silencioso a propósito: la app funciona igual sin service worker
            // (por ejemplo, en navegadores que lo bloquean en HTTP local sin
            // HTTPS) — no es un fallo que amerite molestar al usuario.
        });
    });
}

// Botón "Instalar app": Chrome en Android decide con sus propios criterios
// (no siempre predecibles) cuándo mostrar el aviso automático de
// instalación -- a veces tarda, a veces no aparece nunca aunque el manifest
// y el service worker estén perfectos. `beforeinstallprompt` es el evento
// que el navegador dispara
// cuando SÍ determina que la app es instalable -- en vez de esperar a que
// decida mostrar su propio banner, se guarda ese evento y se muestra un
// botón propio y visible que dispara el mismo diálogo nativo al tocarlo.
// No existe en iOS Safari (ahí la instalación es manual, "Compartir" ->
// "Agregar a inicio") ni si la app ya está instalada -- en esos casos el
// botón simplemente nunca se muestra, se queda oculto (atributo `hidden`
// en el HTML) sin romper nada.
let deferredInstallPrompt = null;

window.addEventListener('beforeinstallprompt', function (e) {
    e.preventDefault();
    deferredInstallPrompt = e;
    document.querySelectorAll('[data-se-install-app]').forEach(function (btn) {
        btn.hidden = false;
    });
});

document.addEventListener('DOMContentLoaded', function () {
    document.querySelectorAll('[data-se-install-app]').forEach(function (btn) {
        btn.addEventListener('click', function () {
            if (!deferredInstallPrompt) return;
            deferredInstallPrompt.prompt();
            deferredInstallPrompt.userChoice.finally(function () {
                deferredInstallPrompt = null;
                btn.hidden = true;
            });
        });
    });
});

// Una vez instalada, no tiene sentido seguir ofreciendo el botón.
window.addEventListener('appinstalled', function () {
    deferredInstallPrompt = null;
    document.querySelectorAll('[data-se-install-app]').forEach(function (btn) {
        btn.hidden = true;
    });
});
