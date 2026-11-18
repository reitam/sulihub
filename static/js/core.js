// KRÉ-14 #97: az index.html inline scriptjének globális része (szó szerinti mozgatás).
// A top-level függvények (formatSchedTime, schedulerCompactState, avatar*, ...) azért
// maradnak globálisak, mert a Playwright-tesztek page.evaluate-ből hívják őket.
// DataTables magyar szövegek beépítve (a korábbi CDN-es JSON CORS-hibát adott,
// és így internet nélkül is működik).
const HU_DT_LANG = {
    emptyTable: "Nincs megjeleníthető adat",
    info: "_START_–_END_ / _TOTAL_ bejegyzés",
    infoEmpty: "0 bejegyzés",
    infoFiltered: "(szűrve: _MAX_ összesből)",
    lengthMenu: "_MENU_ bejegyzés",
    loadingRecords: "Betöltés...",
    processing: "Feldolgozás...",
    search: "Keresés:",
    zeroRecords: "Nincs találat",
    paginate: { first: "Első", last: "Utolsó", next: "Következő", previous: "Előző" },
    aria: { sortAscending: ": növekvő rendezés", sortDescending: ": csökkenő rendezés" }
};

// ── Monogramos avatar a diák oszlophoz ────────────────────────────────
const AVATAR_COLORS = [
    ['#dbeafe', '#1d4ed8'], ['#dcfce7', '#15803d'], ['#fee2e2', '#b91c1c'],
    ['#fef3c7', '#b45309'], ['#ede9fe', '#6d28d9'], ['#cffafe', '#0e7490'],
    ['#fce7f3', '#be185d'], ['#e2e8f0', '#334155']
];
function avatarInitials(name) {
    const parts = String(name || '').trim().split(/\s+/).filter(Boolean);
    if (parts.length >= 3) return (parts[0][0] + parts[1][0] + parts[2][0]).toUpperCase();
    if (parts.length === 2) return (parts[0][0] + parts[1][0]).toUpperCase();
    if (parts.length === 1) return parts[0].slice(0, 2).toUpperCase();
    return '?';
}
function avatarColor(name) {
    let h = 0;
    const s = String(name || '');
    for (let i = 0; i < s.length; i++) h = (h * 31 + s.charCodeAt(i)) >>> 0;
    return AVATAR_COLORS[h % AVATAR_COLORS.length];
}
function renderDiakAvatar(name) {
    const c = avatarColor(name);
    const safe = String(name || '').replace(/"/g, '&quot;');
    return `<span class="d-inline-flex align-items-center gap-2 avatar-cell" title="${safe}">
        <span class="avatar" style="background:${c[0]};color:${c[1]}" title="${safe}">${avatarInitials(name)}</span>
        <span class="avatar-name">${name}</span>
    </span>`;
}

// ── Ütemező visszajelzése: időformázás + a mobil státuszsáv szövege ──────
// (Szándékosan top-level: tiszta függvények, a mobil nézet tesztje közvetlenül hívja.)
function formatSchedTime(iso) {
    if (!iso) return null;
    const d = new Date(String(iso).replace(' ', 'T'));
    if (isNaN(d.getTime())) return null;
    const now = new Date();
    const ma = new Date(now.getFullYear(), now.getMonth(), now.getDate());
    const nap = new Date(d.getFullYear(), d.getMonth(), d.getDate());
    const diff = Math.round((nap - ma) / 86400000);
    const hhmm = d.toLocaleTimeString('hu-HU', { hour: '2-digit', minute: '2-digit' });
    if (diff === 0) return `ma ${hhmm}`;
    if (diff === 1) return `holnap ${hhmm}`;
    if (diff === -1) return `tegnap ${hhmm}`;
    return `${d.toLocaleDateString('hu-HU')} ${hhmm}`;
}

function schedulerHelpText(sched) {
    const health = (sched && sched.health) || {};
    const failed = (health.last_failed_datasets || []).join(', ');
    if (health.last_error_type === 'token') {
        return 'A KRÉTA munkamenet lejárt. A következő szinkron automatikusan ' +
               'megpróbál belépni a config.json-ban megadott felhasználónévvel és ' +
               'jelszóval. Ha ez ismétlődik, ellenőrizd a belépési adatokat, majd ' +
               'indíts kézi frissítést.';
    }
    if ((health.consecutive_errors || 0) >= 3) {
        return (failed ? `Nem frissült: ${failed}. ` : '') +
               'A szinkron több egymást követő alkalommal hibázott. Nézd meg a ' +
               'Rendszernaplót; átmeneti hiba (pl. 503) esetén a következő futás ' +
               'újrapróbálja.';
    }
    if (sched && sched.last_status === 'done_with_errors') {
        return (failed ? `Nem frissült: ${failed}. ` : '') +
               'A többi adat igen. A részletek a Rendszernaplóban láthatók.';
    }
    return '';
}

function schedulerCompactState(sched) {
    if (sched.running) {
        return {
            icon: '<span class="spinner-border spinner-border-sm text-primary" role="status" aria-hidden="true"></span>',
            text: sched.trigger === 'scheduled'
                ? 'Szinkronizálás folyamatban… (auto)'
                : 'Szinkronizálás folyamatban… (kézi)',
            cls: 'text-primary fw-semibold'
        };
    }
    const health = sched.health || {};
    if (health.last_error_type === 'token') {
        return {icon: '<i class="fa-solid fa-key text-danger"></i>',
                text: 'KRÉTA belépés lejárt – koppints a részletekért',
                cls: 'text-danger fw-semibold'};
    }
    if ((health.consecutive_errors || 0) >= 3) {
        return {icon: '<i class="fa-solid fa-triangle-exclamation text-danger"></i>',
                text: `Ismétlődő szinkronhiba (${health.consecutive_errors})`,
                cls: 'text-danger fw-semibold'};
    }
    if (!sched.last_run) {
        return {icon: '<i class="fa-solid fa-circle-minus text-secondary"></i>',
                text: 'Még nem volt szinkronizálás',
                cls: 'text-secondary'};
    }
    const when = formatSchedTime(sched.last_run) || sched.last_run;
    const st = sched.last_status;
    if (st === 'error') {
        return {icon: '<i class="fa-solid fa-circle-xmark text-danger"></i>',
                text: `Sikertelen frissítés (${when})`,
                cls: 'text-danger fw-semibold'};
    }
    if (st === 'done_with_errors') {
        const failed = ((sched.health || {}).last_failed_datasets || []).join(', ');
        return {icon: '<i class="fa-solid fa-triangle-exclamation text-warning"></i>',
                text: `Részben sikerült: ${when}` + (failed ? ` – ${failed}` : ''),
                cls: 'text-warning-emphasis fw-semibold'};
    }
    if (st === 'interrupted' || st === 'stopped') {
        return {icon: '<i class="fa-solid fa-circle-pause text-warning"></i>',
                text: `Megszakadt: ${when}`,
                cls: 'text-warning-emphasis fw-semibold'};
    }
    return {icon: '<i class="fa-solid fa-circle-check text-success"></i>',
            text: `Frissítve: ${when} (${sched.last_trigger === 'scheduled' ? 'auto' : 'kézi'})`,
            cls: 'text-success-emphasis fw-semibold'};
}

function enableResizableTable(tableId) {
    let $table = $('#' + tableId);
    let $headers = $table.find('thead th');

    $headers.each(function() {
        let $th = $(this);
        if ($th.find('.resizer').length === 0) {
            let $resizer = $('<div class="resizer"></div>');
            $th.append($resizer);

            $resizer.on('mousedown', function(e) {
                e.preventDefault();
                e.stopPropagation();
                let startX = e.pageX;
                let startWidth = $th.width();
                let moved = false;
                $resizer.addClass('resizing');

                $(document).on('mousemove.colResize', function(e) {
                    let delta = e.pageX - startX;
                    if (Math.abs(delta) > 1) moved = true;
                    let newWidth = startWidth + delta;
                    if (newWidth > 50) {
                        $th.css('width', newWidth + 'px');
                    }
                });

                $(document).on('mouseup.colResize', function() {
                    $(document).off('.colResize');
                    $resizer.removeClass('resizing');
                    if (moved) {
                        // A húzás utáni kattintás ne érje el a th-t: a DataTables
                        // a fejléc kattintására rendez, ezért az átméretezés
                        // "átállította a sorrendet". A capture-fázisban, egyszer
                        // elnyeljük a következő clicket.
                        document.addEventListener('click', function(clickEv) {
                            clickEv.stopPropagation();
                            clickEv.preventDefault();
                        }, {capture: true, once: true});
                    }
                });
            });

            // A fogantyú saját kattintása se buborékoljon tovább a th-ra.
            $resizer.on('click', function(e) {
                e.preventDefault();
                e.stopPropagation();
            });
        }
    });
}

