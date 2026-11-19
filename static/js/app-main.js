// KRÉ-14 #97: az index.html inline scriptjének fő része (szó szerinti mozgatás,
// a $(document).ready wrapperrel együtt). A vendor scriptek után töltődik.
$(document).ready(function() {
    let rawData = [];
    let rawUzenetek = [];
    let kedvencKulcsok = new Set();
    let syncInterval = null;
    let currentVegosszeg = 0;
    let calendar = null;
    let orarendCalendar = null;

    // A szűrőpanel a fül-sáv ALÁ kerül (az Események fül tartalmába), hogy a
    // felső menüsor pozíciója ne ugráljon a fülek között (Kaneo #121).
    (function () {
        const $blokk = $('#accordionFilterBlock');
        const $pane = $('#esemenyek-pane');
        if ($blokk.length && $pane.length) {
            const $back = $pane.find('.btn-back-dashboard').first();
            $blokk.removeClass('d-none');
            if ($back.length) $blokk.insertAfter($back);
            else $pane.prepend($blokk);
        }
    })();

    let fmtDate = (d) => {
        let year = d.getFullYear();
        let month = String(d.getMonth() + 1).padStart(2, '0');
        let day = String(d.getDate()).padStart(2, '0');
        return `${year}-${month}-${day}`;
    };

    function setDefaultRewardDates() {
        let now = new Date();
        let y = now.getFullYear();
        let m = now.getMonth();
        
        let prevMonthFirstDay = new Date(y, m - 1, 1);
        let currentMonthLastDay = new Date(y, m + 1, 0);

        if (!$('#rewardKezdoDatum').val()) {
            $('#rewardKezdoDatum').val(fmtDate(prevMonthFirstDay));
        }
        if (!$('#rewardZaroDatum').val()) {
            $('#rewardZaroDatum').val(fmtDate(currentMonthLastDay));
        }
    }

    setDefaultRewardDates();

    function getTodayNum() {
        let now = new Date();
        let y = now.getFullYear();
        let m = String(now.getMonth() + 1).padStart(2, '0');
        let d = String(now.getDate()).padStart(2, '0');
        return parseInt(`${y}${m}${d}`, 10);
    }

    function dateToNum(dStr) {
        if (!dStr || dStr === '-') return null;
        let clean = dStr.replace(/[^0-9]/g, '');
        if (clean.length < 8) return null;
        return parseInt(clean.substring(0, 8), 10);
    }

    let dataTable = $('#esemenyekTable').DataTable({
        responsive: true,
        language: HU_DT_LANG,
        // Mobilon ezek az oszlopok maradnak legtovább láthatók (1 = legfontosabb).
        // Az „Érték / Mód” (a jegy) fontosabb, mint a típus-badge: így az
        // értékeléseknél mobilon is alapból látszik maga a jegy (Kaneo #110).
        columnDefs: [
            { targets: 0, responsivePriority: 1 },   // Diák (avatar)
            { targets: 2, responsivePriority: 2 },   // Tantárgy
            { targets: 3, responsivePriority: 3 },   // Érték / Mód (a jegy!)
            { targets: 4, responsivePriority: 4 },   // Bejegyzés dátuma
            { targets: 9, responsivePriority: 5 },   // Műveletek (mindig elérhető)
            { targets: 1, responsivePriority: 6 },   // Típus
            { targets: 7, responsivePriority: 7 },   // Részletek / Leírás
            { targets: 6, responsivePriority: 8 },   // Értékelő / tanár
            { targets: 8, responsivePriority: 9 }    // Bekerült (a SuliHub first seen)
        ],
        pageLength: 25,
        order: [[4, 'desc']],
        autoWidth: false,
        createdRow: function(row, data, dataIndex) {
            let todayNum = getTodayNum();
            let bejNum = dateToNum(data.letrehozva || data.bej_datum);

            if (data.esemeny_tipus === 'Házi feladat' && data.kesz === 1) {
                $(row).addClass('completed-hazi-row');
            } else if (bejNum && bejNum === todayNum) {
                $(row).addClass('today-row');
            }
        },
        columns: [
            { data: 'diak_nev', render: function (data, type) { return type === 'display' ? renderDiakAvatar(data) : data; } },
            {
                data: 'esemeny_tipus',
                render: function(data) {
                    let cls = 'bg-secondary';
                    if (data === 'Értékelés') cls = 'badge-ertekeles';
                    else if (data === 'Feljegyzés') cls = 'badge-feljegyzes';
                    else if (data === 'Házi feladat') cls = 'badge-hazi';
                    else if (data === 'Bejelentett számonkérés') cls = 'badge-szamonkeres';
                    return `<span class="badge ${cls}">${data === 'Bejelentett számonkérés'
                        ? '<span class="d-none d-md-inline">Bejelentett </span>számonkérés'
                        : data}</span>`;
                }
            },
            { data: 'tantargy' },
            { 
                data: null,
                render: function(data) {
                    if (data.esemeny_tipus === 'Értékelés') {
                        let suly = Number(data.suly_szazalek) || 0;
                        // A súly a jegy után jön, hogy a szűk oszlopban ne a mód
                        // miatt csússzon ki (a cella nowrap + ellipsis).
                        let sulyHtml = suly
                            ? ` <span class="badge badge-suly" title="Az értékelés ${suly}%-os súllyal számít bele az átlagba.">${suly}%</span>`
                            : '';
                        let modHtml = data.mod && data.mod !== '-'
                            ? ` <span class="text-muted small">(${data.mod})</span>`
                            : '';
                        let teljes = `${data.ertek}${data.mod && data.mod !== '-' ? ' (' + data.mod + ')' : ''}`
                            + (suly ? ` - ${suly}%` : '');
                        return `<span title="${teljes}"><strong>${data.ertek}</strong>${sulyHtml}${modHtml}</span>`;
                    }
                    if (data.esemeny_tipus === 'Bejelentett számonkérés') return data.mod;
                    return '-';
                }
            },
            { 
                data: 'bej_datum',
                render: function(data) {
                    if (!data || data === '-') return '-';
                    let todayNum = getTodayNum();
                    let bejNum = dateToNum(data);
                    if (bejNum && bejNum === todayNum) {
                        return `<strong class="text-success">${data}</strong> <span class="badge badge-mai">MA</span>`;
                    }
                    return data;
                }
            },
            { 
                data: null,
                render: function(data) {
                    let hDate = data.hatarido;
                    let todayNum = getTodayNum();
                    let hNum = dateToNum(hDate);

                    if (data.esemeny_tipus === 'Házi feladat') {
                        if (data.kesz === 1) {
                            return `${hDate || ''} <span class="badge badge-elkeszult ms-1"><i class="fa-solid fa-check me-1"></i>Elkészítve</span>`;
                        } else if (hNum) {
                            if (hNum >= todayNum) {
                                return `${hDate} <span class="badge badge-aktiv ms-1">Aktív</span>`;
                            } else {
                                return `${hDate} <span class="badge badge-lejart ms-1">Lejárt</span>`;
                            }
                        }
                    }

                    if (data.esemeny_tipus === 'Bejelentett számonkérés' && hNum) {
                        if (hNum >= todayNum) {
                            return `${hDate} <span class="badge badge-aktiv ms-1">Aktív</span>`;
                        } else {
                            return `${hDate} <span class="badge badge-lejart ms-1">Lejárt</span>`;
                        }
                    }
                    return hDate || '-';
                }
            },
            { data: 'ertekelo' },
            {
                data: null,
                render: function(data, type) {
                    let reszletek = [];
                    if (data.tema && data.tema !== '-') reszletek.push(`Téma: ${data.tema}`);
                    if (data.cim && data.cim !== '-') reszletek.push(`Cím: ${data.cim}`);
                    if (data.tartalom && data.tartalom !== '-') reszletek.push(`${data.tartalom}`);
                    let fullText = reszletek.join(' | ') || '-';
                    if (type !== 'display') return fullText;
                    let safeTitle = fullText.replace(/"/g, '&quot;').replace(/'/g, '&#39;');
                    return `<span class="cell-truncate" title="${safeTitle}">${fullText}</span>`;
                }
            },
            {
                data: 'letrehozva',
                render: function (data, type) {
                    if (type !== 'display') return data || '';
                    if (!data) return '-';
                    let nap = String(data).slice(0, 10);
                    let cim = String(data).replace(/"/g, '&quot;');
                    let num = dateToNum(nap);
                    if (num && num === getTodayNum()) {
                        return `<span title="${cim}"><strong class="text-success">${nap}</strong> <span class="badge badge-mai">MA</span></span>`;
                    }
                    return `<span title="${cim}">${nap}</span>`;
                }
            },
            {
                data: null,
                orderable: false,
                searchable: false,
                render: function(data, type) {
                    if (type !== 'display') return '';
                    let reszletek = [];
                    if (data.tema && data.tema !== '-') reszletek.push(`Téma: ${data.tema}`);
                    if (data.cim && data.cim !== '-') reszletek.push(`Cím: ${data.cim}`);
                    if (data.tartalom && data.tartalom !== '-') reszletek.push(`${data.tartalom}`);
                    let fullText = reszletek.join(' | ') || '-';
                    let safeTitle = fullText.replace(/"/g, '&quot;').replace(/'/g, '&#39;');

                    let btnKeszHtml = '';
                    if (data.esemeny_tipus === 'Házi feladat') {
                        if (data.kesz === 1) {
                            btnKeszHtml = `<button class="btn btn-xs btn-outline-secondary py-0 px-1 btn-toggle-kesz" data-id="${data.id}" data-kesz="0" title="Visszaállítás elkészítendőre">
                                <i class="fa-solid fa-rotate-left me-1"></i>Újra aktív
                            </button>`;
                        } else {
                            btnKeszHtml = `<button class="btn btn-xs btn-success text-white py-0 px-1 btn-toggle-kesz" data-id="${data.id}" data-kesz="1" title="Megjelölés elkészültként">
                                <i class="fa-solid fa-check me-1"></i>Elkészült
                            </button>`;
                        }
                    }

                    let btnDetailsHtml = `<button class="btn btn-xs btn-outline-primary py-0 px-1 btn-show-details" data-id="${data.id}" data-text="${safeTitle}" title="Részletek megtekintése">
                        <i class="fa-solid fa-magnifying-glass"></i>
                    </button>`;

                    let btnKommentHtml = `<button class="btn btn-xs btn-outline-secondary py-0 px-1 btn-show-komment"
                        data-kulcs="${data.komment_kulcs || ''}"
                        data-diak="${escapeHtml(data.diak_nev || '')}"
                        data-db="${data.komment_db || 0}"
                        title="Saját megjegyzés (${data.komment_db || 0})">
                        <i class="fa-solid fa-comment-dots"></i>${data.komment_db ? ' ' + data.komment_db : ''}
                    </button>`;

                    let kedvenc = kedvencKulcsok.has(data.komment_kulcs);
                    let btnKedvencHtml = `<button class="btn btn-xs btn-outline-warning py-0 px-1 btn-kedvenc"
                        data-kulcs="${data.komment_kulcs || ''}"
                        title="${kedvenc ? 'Kitűzés levétele' : 'Kitűzés a dashboardra'}">
                        <i class="${kedvenc ? 'fa-solid' : 'fa-regular'} fa-star"></i>
                    </button>`;

                    return `<div class="d-flex align-items-center gap-1 justify-content-end">
                        ${btnKeszHtml}
                        ${btnKedvencHtml}
                        ${btnKommentHtml}
                        ${btnDetailsHtml}
                    </div>`;
                }
            }
        ],
        drawCallback: function() {
            enableResizableTable('esemenyekTable');

    // A Responsive a betöltéskori szélességgel számol — mobilon újra kell számolni,
    // különben a táblázat szélesebb marad az ablaktörzsnál.
    setTimeout(function() {
        try { if (dataTable.responsive) dataTable.responsive.recalc(); } catch (e) {}
    }, 120);
    $(window).on('resize orientationchange', function() {
        clearTimeout(window.__kretaResizeT);
        window.__kretaResizeT = setTimeout(function() {
            try { if (dataTable.responsive) dataTable.responsive.recalc(); } catch (e) {}
            try { if (typeof uzenetekTable !== 'undefined' && uzenetekTable.responsive) uzenetekTable.responsive.recalc(); } catch (e) {}
        }, 200);
    });
        }
    });

    let uzenetOlvasottMode = 'all';
    let uzenetKijelolt = new Set();

    function updateUzenetOlvasatlanBadge() {
        let cnt = 0;
        (rawUzenetek || []).forEach(function(m) {
            if (!m.olvasott) cnt++;
        });
        let $b = $('#uzenetekOlvasatlanBadge');
        if (cnt > 0) {
            $b.text(cnt).removeClass('d-none');
        } else {
            $b.text('0').addClass('d-none');
        }
    }

    // Kijelölés (checkbox) állapotának frissítése a lista újrarajzolása után.
    function updateUzenetKijeloles() {
        let $bar = $('#uzenetBulkBar');
        let n = uzenetKijelolt.size;
        $('#uzenetKijeloltDb').text(n);
        $bar.toggleClass('d-none', n === 0);
        // A fejléc "mind" pipa állapota a látható (szűrt) sorok alapján.
        let $all = $('#uzenetSelectAll');
        let total = uzenetekTable.rows({ search: 'applied' }).count();
        let selected = 0;
        uzenetekTable.rows({ search: 'applied' }).every(function() {
            let d = this.data();
            if (d && uzenetKijelolt.has(d.id)) selected++;
        });
        $all.prop('checked', total > 0 && selected === total)
            .prop('indeterminate', selected > 0 && selected < total);
    }

    $.fn.dataTable.ext.search.push(function(settings, data, dataIndex, rowData) {
        if (!settings.nTable || settings.nTable.id !== 'uzenetekTable') return true;
        if (uzenetOlvasottMode === 'unread') return !rowData.olvasott;
        if (uzenetOlvasottMode === 'read') return !!rowData.olvasott;
        return true;
    });

    let uzenetekTable = $('#uzenetekTable').DataTable({
        responsive: true,
        language: HU_DT_LANG,
        columnDefs: [
            { targets: 0, responsivePriority: 0, orderable: false, searchable: false, className: 'text-center' }, // Kijelölés
            { targets: 3, responsivePriority: 1 },   // Tárgy (a legfontosabb)
            { targets: 1, responsivePriority: 2 },   // Diák
            { targets: 2, responsivePriority: 3 },   // Feladó
            { targets: 6, responsivePriority: 4 }    // Művelet
        ],
        pageLength: 25,
        order: [[4, 'desc']],
        autoWidth: false,
        createdRow: function(row, data, dataIndex) {
            let todayNum = getTodayNum();
            let msgNum = dateToNum(data.letrehozva || data.idopont);
            if (msgNum && msgNum === todayNum) {
                $(row).addClass('today-row');
            }
            $(row).toggleClass('uzenet-olvasatlan', !data.olvasott);
        },
        columns: [
            {
                data: null,
                orderable: false,
                searchable: false,
                render: function(data, type, row) {
                    if (type !== 'display') return '';
                    let checked = uzenetKijelolt.has(row.id) ? 'checked' : '';
                    return `<input type="checkbox" class="form-check-input m-0 uzenet-select"
                                   data-id="${row.id}" ${checked}
                                   title="Kijelölés tömeges állapotváltáshoz">`;
                }
            },
            { data: 'diak_nev', render: function (data, type) { return type === 'display' ? renderDiakAvatar(data) : data; } },
            { data: 'felado' },
            { 
                data: 'targy',
                render: function(data, type, row) {
                    if (type === 'filter') {
                        return (data || '') + ' ' + ((row && row.szoveg) || '');
                    }
                    if (type !== 'display') return data || '';
                    let safeText = (data || '').replace(/"/g, '&quot;');
                    let dot = row.olvasott ? '' : '<span class="uzenet-status-dot me-1" title="Olvasatlan"></span>';
                    return `${dot}<span class="cell-truncate" title="${safeText}">${data || '-'}</span>`;
                }
            },
            { 
                data: 'idopont',
                render: function(data) {
                    if (!data || data === '-') return '-';
                    let todayNum = getTodayNum();
                    let msgNum = dateToNum(data);
                    if (msgNum && msgNum === todayNum) {
                        return `<strong class="text-success">${data}</strong> <span class="badge badge-mai">MA</span>`;
                    }
                    return data;
                }
            },
            { 
                data: null,
                render: function(data) {
                    if (data.csatolmany_nev) {
                        return `<span class="badge bg-primary cell-truncate" title="${data.csatolmany_nev}"><i class="fa-solid fa-paperclip me-1"></i>${data.csatolmany_nev}</span>`;
                    }
                    return '-';
                }
            },
            { 
                data: null,
                render: function(data, type, row, meta) {
                    let toggleIcon = row.olvasott ? 'fa-envelope' : 'fa-envelope-open';
                    let toggleTitle = row.olvasott ? 'Megjelölés olvasatlanként' : 'Megjelölés olvasottként';
                    let toggleCls = row.olvasott ? 'btn-outline-secondary' : 'btn-outline-primary';
                    return `<div class="d-inline-flex gap-1 align-items-center">
                        <button class="btn btn-sm btn-info text-dark py-0 px-2 btn-read-msg" data-id="${row.id}" data-index="${meta.row}">
                            <i class="fa-solid fa-eye me-1"></i>Olvasás
                        </button>
                        <button class="btn btn-sm ${toggleCls} py-0 px-1 btn-toggle-msg-read d-none d-sm-inline-block" data-id="${row.id}" title="${toggleTitle}">
                            <i class="fa-solid ${toggleIcon}"></i>
                        </button>
                    </div>`;
                }
            }
        ],
        drawCallback: function() {
            enableResizableTable('uzenetekTable');

    setTimeout(function() {
        try { updateUzenetKijeloles(); } catch (e) {}
        try { if (uzenetekTable.responsive) uzenetekTable.responsive.recalc(); } catch (e) {}
    }, 120);
        }
    });

    // ── HIÁNYZÁSOK / KÉSÉSEK ÉS IGAZOLÁSOK ────────────────────────────────
    function escapeHtml(value) {
        return String(value === null || value === undefined ? '' : value)
            .replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;')
            .replace(/"/g, '&quot;').replace(/'/g, '&#39;');
    }

    // A KRÉTA az igazolás megjegyzését HTML-ként adja (pl. <p>…</p>);
    // megjelenítés előtt sima szövegre alakítjuk.
    function htmlToText(value) {
        if (value === null || value === undefined) return '';
        let s = String(value);
        if (s.indexOf('<') === -1) return s;
        s = s.replace(/<\/(p|div|li|tr|h[1-6]|td|th)>/gi, ' ').replace(/<br\s*\/?>/gi, ' ');
        let d = document.createElement('div');
        d.innerHTML = s;
        return (d.textContent || d.innerText || '').replace(/\s+/g, ' ').trim();
    }

    function fmtIsoToHu(value) {        if (!value) return '-';
        let parts = String(value).split('-');
        if (parts.length !== 3) return value;
        return `${parts[0]}. ${parts[1]}. ${parts[2]}.`;
    }

    let hianyzasokTable = $('#hianyzasokTable').DataTable({
        responsive: true,
        language: HU_DT_LANG,
        columnDefs: [
            { targets: 1, responsivePriority: 1 },   // Dátum
            { targets: 2, responsivePriority: 2 },   // Típus
            { targets: 0, responsivePriority: 3 },   // Diák
            { targets: 6, responsivePriority: 4 },   // Igazolt?
            { targets: 4, responsivePriority: 5 }    // Tantárgy
        ],
        pageLength: 25,
        order: [[1, 'desc']],
        autoWidth: false,
        columns: [
            { data: 'diak_nev', render: function (data, type) { return type === 'display' ? renderDiakAvatar(data) : data; } },
            { data: 'mulasztas_datum', render: function (data, type) { return type === 'display' ? fmtIsoToHu(data) : data; } },
            {
                data: 'mulasztas_tipus',
                render: function (data, type, row) {
                    if (type !== 'display') return data;
                    let nev = data || '-';
                    if (row.keses && row.perc) {
                        nev = (data || 'Késés') + ` (${row.perc} perc)`;
                    }
                    let cls = row.keses ? 'bg-warning text-dark' : 'bg-danger';
                    return `<span class="badge ${cls}">${escapeHtml(nev)}</span>`;
                }
            },
            { data: 'ora_sorszam', render: function (data) { return Number(data) ? data + '. óra' : '-'; } },
            { data: 'tantargy', render: function (data) { let t = data || '-'; return `<span title="${escapeHtml(t)}">${escapeHtml(t)}</span>`; } },
            { data: 'tema', render: function (data) { let t = data || '-'; return `<span title="${escapeHtml(t)}">${escapeHtml(t)}</span>`; } },
            {
                data: 'igazolt',
                render: function (data, type) {
                    if (type !== 'display') return data;
                    return Number(data) === 1
                        ? '<span class="badge bg-success">Igazolt</span>'
                        : '<span class="badge bg-danger">Igazolatlan</span>';
                }
            },
            { data: 'igazolas_tipus', render: function (data) { let t = data || '-'; return `<span title="${escapeHtml(t)}">${escapeHtml(t)}</span>`; } }
        ],
        drawCallback: function () {
            enableResizableTable('hianyzasokTable');
            setTimeout(function () {
                try { if (hianyzasokTable.responsive) hianyzasokTable.responsive.recalc(); } catch (e) {}
            }, 120);
        }
    });

    let igazolasokTable = $('#igazolasokTable').DataTable({
        responsive: true,
        language: HU_DT_LANG,
        columnDefs: [
            { targets: 1, responsivePriority: 1 },   // Kezdete
            { targets: 3, responsivePriority: 2 },   // Típus
            { targets: 0, responsivePriority: 3 },   // Diák
            { targets: 2, responsivePriority: 4 },   // Vége
            { targets: 4, responsivePriority: 5 }    // Megjegyzés
        ],
        pageLength: 25,
        order: [[1, 'desc']],
        autoWidth: false,
        columns: [
            { data: 'diak_nev', render: function (data, type) { return type === 'display' ? renderDiakAvatar(data) : data; } },
            { data: 'kezdete', render: function (data, type) { return type === 'display' ? fmtIsoToHu(data) : data; } },
            { data: 'vege', render: function (data, type) { return type === 'display' ? fmtIsoToHu(data) : data; } },
            { data: 'igazolas_tipus', render: function (data) { let t = data || '-'; return `<span title="${escapeHtml(t)}">${escapeHtml(t)}</span>`; } },
            { data: 'megjegyzes', render: function (data) { let t = htmlToText(data) || '-'; return `<span title="${escapeHtml(t)}">${escapeHtml(t)}</span>`; } }
        ],
        drawCallback: function () {
            enableResizableTable('igazolasokTable');
            setTimeout(function () {
                try { if (igazolasokTable.responsive) igazolasokTable.responsive.recalc(); } catch (e) {}
            }, 120);
        }
    });

    function setDefaultHianyzasMonth() {
        let now = new Date();
        let aktualis = `${now.getFullYear()}-${String(now.getMonth() + 1).padStart(2, '0')}`;
        // Ha a kiválasztott tanév nem tartalmazza az aktuális hónapot, ne állítsuk be
        // (Kaneo #53): a hónapválasztó a tanév határain belül marad.
        let h = aktualisTanevHatar();
        if (h && (aktualis < h.kezdo.slice(0, 7) || aktualis > h.zaro.slice(0, 7))) {
            $('#hianyzasHonap').val('');
            return;
        }
        $('#hianyzasHonap').val(aktualis);
    }

    function loadHianyzasok() {
        let params = new URLSearchParams();
        let diak = $('#hianyzasFilterDiak').val() || '';
        let honap = $('#hianyzasHonap').val() || '';
        let tanev = kivalasztottTanev();
        if (diak) params.set('diak', diak);
        if (honap) params.set('honap', honap);
        if (tanev) params.set('tanev', tanev);

        $.getJSON('/api/hianyzasok?' + params.toString(), function (res) {
            let rows = (res && res.rows) || [];
            let o = (res && res.osszesito) || {};
            hianyzasokTable.clear().rows.add(rows).draw();
            $('#stHianyzasOra').text((o.hianyzas_db || 0) + ' óra');
            $('#stIgazoltOra').text((o.igazolt_ora || 0) + ' óra');
            $('#stIgazolatlanOra').text((o.igazolatlan_ora || 0) + ' óra');
            $('#stKesesDb').text((o.keses_db || 0) + ' db');
            $('#stKesesPerc').text((o.keses_perc || 0) + ' perc');

            let honapSzoveg = honap ? (honap.replace('-', '. ') + '.') : '';
            $('#hianyzasModHint').html(honap
                ? `<i class="fa-solid fa-filter me-1"></i>Csak a(z) <b>${escapeHtml(honapSzoveg)}</b> hiányzásai látszanak.`
                : '<i class="fa-solid fa-list me-1"></i><b>Összes időszak</b> — havi bontáshoz válassz hónapot.');

            let hint = $('#hianyzasEmptyHint');
            if (!rows.length && (honap || tanev)) {
                let reszek = [];
                if (honap) reszek.push(`Ebben a hónapban (${escapeHtml(honapSzoveg)}) nincs hiányzás.`);
                if (tanev) reszek.push(`A(z) <b>${escapeHtml(tanev)}. tanévben</b> nincs hiányzás.`);
                hint.removeClass('d-none').html(
                    `<i class="fa-solid fa-circle-info me-1"></i>${reszek.join(' ')} ` +
                    'Az <b>Összes</b> gomb a hónap-szűrőt törli, a tanév a fejlécben váltható.');
            } else {
                hint.addClass('d-none');
            }
        });

        $.getJSON('/api/igazolasok?' + params.toString(), function (rows) {
            let lista = rows || [];
            igazolasokTable.clear().rows.add(lista).draw();
            $('#stIgazolasDb').text(lista.length + ' db');

            let hint = $('#igazolasEmptyHint');
            if (!lista.length && honap) {
                hint.removeClass('d-none').html(
                    '<i class="fa-solid fa-circle-info me-1"></i>Ebben a hónapban nincs igazolás — az <b>Összes</b> gombbal a teljes lista látható.');
            } else {
                hint.addClass('d-none');
            }
        });

        loadHianyzasMintazat();
    }

    // Alapból a teljes előzmény látszik (nehogy egy üres aktuális hónap miatt
    // úgy tűnjön, mintha nem jöttek volna le az adatok). A havi bontás a
    // "Aktuális hónap" gombbal vagy a hónapválasztóval érhető el.
    $('#hianyzasFilterDiak, #hianyzasHonap').change(function () {
        loadHianyzasok();
    });

    $('#btnHianyzasThisMonth').click(function () {
        setDefaultHianyzasMonth();
        loadHianyzasok();
    });

    $('#btnHianyzasAll').click(function () {
        $('#hianyzasHonap').val('');
        loadHianyzasok();
    });

    // --- ÓRAREND NAPTÁR INICIALIZÁLÁSA ---
    function initOrarendCalendar() {
        let calendarEl = document.getElementById('orarendCalendar');
        if (!calendarEl || orarendCalendar) return;

        orarendCalendar = new FullCalendar.Calendar(calendarEl, {
            locale: 'hu',
            initialView: window.innerWidth < 768 ? 'timeGridDay' : 'timeGridWeek',
            slotDuration: '00:15:00',
            slotLabelInterval: '01:00:00',
            slotMinTime: '07:00:00',
            slotMaxTime: '17:00:00',
            slotEventOverlap: true,
            allDaySlot: true,
            height: 'auto',
            displayEventTime: true,
            headerToolbar: {
                left: 'prev,next today',
                center: 'title',
                right: window.innerWidth < 768 ? 'timeGridDay,timeGridWeek' : 'timeGridWeek,timeGridDay'
            },
            buttonText: {
                today: 'Ma',
                week: 'Hét',
                day: 'Nap'
            },
            events: function(info, successCallback, failureCallback) {
                let selectedDiak = $('#orarendFilterDiak').val() || $('#filterDiak').val();
                $.getJSON(`/api/orarend_naptar?diak=${encodeURIComponent(selectedDiak)}`
                          + `&start=${encodeURIComponent(info.startStr)}&end=${encodeURIComponent(info.endStr)}`,
                          function(data) {
                    successCallback(data);
                }).fail(function() {
                    failureCallback();
                });
            },
            eventClick: function(info) {
                let props = info.event.extendedProps;
                let actionContainer = $('#modalActionContainer');
                actionContainer.empty();

                if (props.sajat) {
                    aktualisSajatProps = props;
                    let bodyText = `Diák: ${props.diak}\nMegnevezés: ${props.cim || props.tantargy}`
                        + `\nIdőpont: ${props.datum} ${props.kezdes}–${props.vege}`
                        + `\nTerem / helyszín: ${props.terem || '-'}`
                        + `\nÉrvényesség: ${props.ervenyes_tol} – ${props.ervenyes_ig}`
                        + `\nMegjegyzés: ${props.megjegyzes || '-'}`;
                    $('#detailsModalTitle').html(`<i class="fa-solid fa-calendar-plus me-2"></i>${info.event.title}`);
                    reszletekBody(bodyText);
                    actionContainer.removeClass('d-none').html(`
                        <div class="d-flex gap-2 justify-content-end flex-wrap">
                            <button class="btn btn-sm btn-outline-primary btn-sajat-szerkeszt" data-id="${props.sajat_id}">
                                <i class="fa-solid fa-pen me-1"></i>Módosítás
                            </button>
                            <button class="btn btn-sm btn-outline-danger btn-sajat-kivetel"
                                    data-id="${props.sajat_id}" data-datum="${props.datum}">
                                <i class="fa-solid fa-calendar-xmark me-1"></i>Csak ezt az alkalmat törli
                            </button>
                            <button class="btn btn-sm btn-danger btn-sajat-sorozat" data-id="${props.sajat_id}">
                                <i class="fa-solid fa-trash me-1"></i>Teljes sorozat törlése
                            </button>
                        </div>`);
                } else {
                    let bodyText = `Diák: ${props.diak}\nÓra / Esemény: ${props.tantargy}\nTanár: ${props.tanar || '-'}\nTerem: ${props.terem || '-'}`;
                    $('#detailsModalTitle').html(`<i class="fa-solid fa-clock me-2"></i>${info.event.title}`);
                    reszletekBody(bodyText);
                    actionContainer.addClass('d-none');
                }

                let detailsModal = new bootstrap.Modal(document.getElementById('detailsModal'));
                detailsModal.show();
            }
        });

        orarendCalendar.render();
    }

    // --- HÁZI FELADATOK NAPTÁR INICIALIZÁLÁSA ---
    function initCalendar() {
        let calendarEl = document.getElementById('calendar');
        if (!calendarEl || calendar) return;

        calendar = new FullCalendar.Calendar(calendarEl, {
            locale: 'hu',
            initialView: window.innerWidth < 768 ? 'listWeek' : 'dayGridWeek',
            height: 'auto',
            displayEventTime: false,
            headerToolbar: {
                left: 'prev,next today',
                center: 'title',
                right: window.innerWidth < 768 ? 'monthList,weekList' : 'dayGridMonth,dayGridWeek,listMonth'
            },
            // Külön névvel ellátott lista-nézetek (különben mindkét gomb "Lista" lenne)
            views: {
                weekList: { type: 'listWeek', buttonText: 'Heti lista' },
                monthList: { type: 'listMonth', buttonText: 'Havi lista' }
            },
            buttonText: {
                today: 'Ma',
                month: 'Hónap',
                week: 'Hét'
            },
            events: function(info, successCallback, failureCallback) {
                let selectedDiak = $('#naptarFilterDiak').val();
                $.getJSON(`/api/naptar_esemenyek?diak=${encodeURIComponent(selectedDiak)}`, function(data) {
                    successCallback(data);
                }).fail(function() {
                    failureCallback();
                });
            },
            eventClick: function(info) {
                let props = info.event.extendedProps;
                let eventId = info.event.id;

                // Egységes részletek modál — ugyanaz a szerkezet, mint az
                // esemény-táblában (Kaneo #126: a naptárból nyitva is tagolt).
                reszletekModal(props.tipus, esemenyReszletekSzoveg({
                    diak_nev: props.diak_nev || props.diak,
                    esemeny_tipus: props.esemeny_tipus || props.tipus,
                    tantargy: props.tantargy,
                    ertek: props.ertek,
                    mod: props.mod,
                    bej_datum: props.bej_datum,
                    hatarido: props.hatarido,
                    ertekelo: props.ertekelo || props.tanar,
                    tema: props.tema,
                    cim: props.cim,
                    tartalom: props.tartalom,
                    suly_szazalek: props.suly_szazalek,
                    kesz: props.kesz
                }));

                let actionContainer = $('#modalActionContainer');
                actionContainer.empty();

                let actions = [];
                if (props.tipus === 'Házi feladat') {
                    if (props.kesz) {
                        actions.push(`<button class="btn btn-sm btn-outline-secondary btn-modal-toggle-kesz" data-id="${eventId}" data-kesz="0">
                            <i class="fa-solid fa-rotate-left me-1"></i>Visszaállítás elkészítendőre
                        </button>`);
                    } else {
                        actions.push(`<button class="btn btn-sm btn-success text-white btn-modal-toggle-kesz" data-id="${eventId}" data-kesz="1">
                            <i class="fa-solid fa-check me-1"></i>Megjelölés elkészültként
                        </button>`);
                    }
                }
                if (props.tipus === 'Házi feladat' || props.tipus === 'Bejelentett számonkérés') {
                    actions.push(`<button class="btn btn-sm btn-primary btn-naptar-google" data-kind="esemeny" data-id="${eventId}"
                        title="Előre kitöltött Google Naptár esemény nyílik; ott egy kattintással menthető">
                        <i class="fa-brands fa-google me-1"></i>Naptárba küldés
                    </button>`);
                }
                if (actions.length) {
                    actionContainer.removeClass('d-none').html(
                        `<div class="d-flex gap-2 justify-content-end flex-wrap">${actions.join('')}</div>`);
                } else {
                    actionContainer.addClass('d-none');
                }
            }
        });

        calendar.render();
    }

    // --- SYNC.LOG NÉZET KEZELÉSE ---
    function fetchSyncLogFile() {
        $.getJSON('/api/logs', function(res) {
            if (res.status === 'ok') {
                let $term = $('#syncLogFileTerminal');
                $term.text(res.content);
                $term.scrollTop($term[0].scrollHeight);
            }
        });
    }

    // ── Legutóbbi futások (Kaneo #10) ─────────────────────────────────────
    function syncRunStatus(status) {
        if (status === 'done') return {text: 'sikeres', cls: 'bg-success'};
        if (status === 'done_with_errors') return {text: 'részleges hiba', cls: 'bg-warning text-dark'};
        if (status === 'error') return {text: 'hiba', cls: 'bg-danger'};
        if (status === 'running') return {text: 'fut...', cls: 'bg-primary'};
        if (status === 'stopped') return {text: 'leállítva', cls: 'bg-secondary'};
        if (status === 'interrupted') return {text: 'megszakadt', cls: 'bg-warning text-dark'};
        return {text: status || '-', cls: 'bg-secondary'};
    }
    function syncRunDuration(sec) {
        let n = Math.round(Number(sec) || 0);
        if (n <= 0) return '-';
        if (n < 60) return n + ' s';
        return Math.floor(n / 60) + 'p ' + String(n % 60).padStart(2, '0') + 's';
    }
    function loadSyncRuns() {
        $.getJSON('/api/sync_runs?limit=20', function(rows) {
            let tbody = $('#syncRunsTable tbody').empty();
            let spark = $('#syncRunsSparkline').empty();
            if (!rows || !rows.length) {
                tbody.append('<tr><td colspan="6" class="text-muted small">Még nincs rögzített futás.</td></tr>');
                $('#syncRunsSummary').text('');
                return;
            }
            let maxDur = Math.max.apply(null, rows.map(r => Number(r.duration_sec) || 0).concat([1]));
            // A sparkline balról jobbra: legrégebbi → legutóbbi
            rows.slice().reverse().forEach(function(r) {
                let st = syncRunStatus(r.status);
                let h = Math.max(6, Math.round(((Number(r.duration_sec) || 0) / maxDur) * 100));
                let bar = $('<div></div>')
                    .css({width: '8px', height: h + '%', borderRadius: '2px'})
                    .addClass(st.cls)
                    .attr('title', `${r.started_at || '-'} · ${syncRunDuration(r.duration_sec)} · ${st.text}`);
                spark.append(bar);
            });
            let failedRuns = 0;
            rows.forEach(function(r) {
                let st = syncRunStatus(r.status);
                let failed = (r.failed_students || []).join(', ');
                if (r.status === 'done_with_errors' || r.status === 'error' || r.status === 'interrupted') failedRuns++;
                tbody.append(`<tr>
                    <td class="small text-nowrap">${formatSchedTime(r.started_at) || r.started_at || '-'}</td>
                    <td class="small text-nowrap">${syncRunDuration(r.duration_sec)}</td>
                    <td><span class="badge ${st.cls}">${st.text}</span></td>
                    <td class="small">${r.new_event_count || 0}</td>
                    <td class="small">${failed || '-'}</td>
                    <td class="small">${r.tanev || '-'}</td>
                </tr>`);
            });
            $('#syncRunsSummary').text(`${rows.length} futás · ${failedRuns} hibás/részleges`);
        });
    }

    $(document).on('click', '.btn-modal-toggle-kesz', function(e) {
        e.stopPropagation();
        let esemenyId = $(this).data('id');
        let ujKesz = $(this).data('kesz');

        $.ajax({
            url: '/api/esemeny/statusz',
            type: 'POST',
            contentType: 'application/json',
            data: JSON.stringify({
                id: esemenyId,
                kesz: ujKesz
            }),
            success: function(res) {
                if (res.status === 'ok') {
                    let detailsModalEl = document.getElementById('detailsModal');
                    let modalInstance = bootstrap.Modal.getInstance(detailsModalEl);
                    if (modalInstance) modalInstance.hide();

                    let item = rawData.find(x => x.id == esemenyId);
                    if (item) {
                        item.kesz = res.kesz;
                    }
                    applyFilters();
                    if (calendar) {
                        calendar.refetchEvents();
                    }
                }
            }
        });
    });

    $('#naptarFilterDiak').change(function() {
        if (calendar) {
            calendar.refetchEvents();
        }
    });

    $('#btnExportOrarendPdf').click(function() {
        let selectedDiak = $('#orarendFilterDiak').val() || $('#filterDiak').val() || '';
        // A naptárban éppen megjelenített hét kezdőnapja — a PDF ehhez a héthez készül
        // (nem fixen az aktuálishoz). A backend a hét hétfőjét számolja belőle.
        let datum = '';
        if (orarendCalendar && orarendCalendar.view && orarendCalendar.view.currentStart) {
            let vs = orarendCalendar.view.currentStart;
            let y = vs.getFullYear();
            let m = String(vs.getMonth() + 1).padStart(2, '0');
            let d = String(vs.getDate()).padStart(2, '0');
            datum = `${y}-${m}-${d}`;
        }
        let url = `/api/orarend/export_pdf?diak=${encodeURIComponent(selectedDiak)}&datum=${encodeURIComponent(datum)}`;
        window.open(url, '_blank');
    });
	
    $('.btn-orarend-ics').click(function() {
        let selectedDiak = $('#orarendFilterDiak').val() || $('#filterDiak').val() || '';
        let period = $(this).data('period') || 'het';
        let datum = '';
        if (orarendCalendar && orarendCalendar.view && orarendCalendar.view.currentStart) {
            let vs = orarendCalendar.view.currentStart;
            datum = `${vs.getFullYear()}-${String(vs.getMonth() + 1).padStart(2, '0')}-${String(vs.getDate()).padStart(2, '0')}`;
        }
        let url = `/api/orarend/export_ics?diak=${encodeURIComponent(selectedDiak)}`
                + `&period=${encodeURIComponent(period)}&datum=${encodeURIComponent(datum)}`;
        window.location.href = url;
    });

	$('#orarendFilterDiak').change(function() {
        if (orarendCalendar) {
            orarendCalendar.refetchEvents();
        }
    });

    // ── Saját óra rögzítése / törlése (Kaneo #55) ─────────────────────────
    function sajatOraIsoDate(d) {
        return `${d.getFullYear()}-${String(d.getMonth() + 1).padStart(2, '0')}-${String(d.getDate()).padStart(2, '0')}`;
    }
    function sajatOraHiba(msg) {
        let box = $('#sajatOraHiba');
        if (msg) box.removeClass('d-none').text(msg);
        else box.addClass('d-none').text('');
    }

    $('#btnSajatOra').click(function() {
        sajatOraHiba('');
        $('#sajatOraEditId').val('');
        $('#sajatOraModalTitle').text('Saját óra rögzítése');
        $('#btnSajatOraMent').html('<i class="fa-solid fa-check me-1"></i>Rögzítés');
        $('#sajatOraCim').val('');
        $('#sajatOraTerem').val('');
        $('#sajatOraMegjegyzes').val('');
        $('#sajatOraKezdes').val('16:00');
        $('#sajatOraVege').val('17:00');
        $('#sajatOraErveny').val('tanev').trigger('change');
        let filterDiak = $('#orarendFilterDiak').val();
        if (filterDiak) $('#sajatOraDiak').val(filterDiak);
        $('#sajatOraSzin').val('#6f42c1');
        $.getJSON('/api/orarend_szinek', function(res) {
            let base = String(((res.szinek || {})[$('#sajatOraDiak').val()] || '')).toLowerCase();
            if (base === '#6f42c1') $('#sajatOraSzin').val('#d63384');
        });
        let ma = new Date();
        $('#sajatOraNap').val(String(ma.getDay() === 0 ? 7 : ma.getDay()));
        $('#sajatOraTol').val(sajatOraIsoDate(ma));
        $('#sajatOraIg').val(sajatOraIsoDate(new Date(ma.getFullYear(), ma.getMonth(), ma.getDate() + 7)));
        new bootstrap.Modal(document.getElementById('sajatOraModal')).show();
    });

    $('#sajatOraErveny').change(function() {
        $('#sajatOraEgyedi').toggleClass('d-none', $(this).val() !== 'egyedi');
    });

    $('#btnSajatOraMent').click(function() {
        sajatOraHiba('');
        let diak = $('#sajatOraDiak').val();
        let cim = $('#sajatOraCim').val().trim();
        let kezdes = $('#sajatOraKezdes').val();
        let vege = $('#sajatOraVege').val();
        let mode = $('#sajatOraErveny').val();
        if (!diak) return sajatOraHiba('Válassz diákot.');
        if (!cim) return sajatOraHiba('A megnevezés kötelező.');
        if (!kezdes || !vege || vege <= kezdes) {
            return sajatOraHiba('A vég időpontjának később kell lennie a kezdésnél.');
        }
        let body = {
            diak_nev: diak,
            cim: cim,
            nap: parseInt($('#sajatOraNap').val(), 10),
            kezdes: kezdes,
            vege: vege,
            terem: $('#sajatOraTerem').val().trim(),
            megjegyzes: $('#sajatOraMegjegyzes').val().trim(),
            szin: $('#sajatOraSzin').val(),
            ervenyesites: mode
        };
        if (mode === 'egyedi') {
            body.tol = $('#sajatOraTol').val();
            body.ig = $('#sajatOraIg').val();
            if (!body.tol || !body.ig) {
                return sajatOraHiba('Az egyedi időszakhoz a kezdő és záró dátum is kell.');
            }
        }
        let btn = $(this).prop('disabled', true);
        let editId = $('#sajatOraEditId').val();
        let url = editId ? `/api/sajat_orarend/${editId}` : '/api/sajat_orarend';
        $.ajax({
            url: url,
            type: editId ? 'PUT' : 'POST',
            contentType: 'application/json',
            data: JSON.stringify(body)
        }).done(function() {
            let modal = bootstrap.Modal.getInstance(document.getElementById('sajatOraModal'));
            if (modal) modal.hide();
            if (orarendCalendar) orarendCalendar.refetchEvents();
        }).fail(function(xhr) {
            sajatOraHiba((xhr.responseJSON && xhr.responseJSON.message) || 'A mentés nem sikerült.');
        }).always(function() {
            btn.prop('disabled', false);
        });
    });

    $(document).on('click', '.btn-sajat-szerkeszt', function() {
        let p = aktualisSajatProps;
        if (!p) return;
        let modal = bootstrap.Modal.getInstance(document.getElementById('detailsModal'));
        if (modal) modal.hide();
        sajatOraHiba('');
        $('#sajatOraEditId').val(p.sajat_id);
        $('#sajatOraModalTitle').text('Saját óra módosítása');
        $('#btnSajatOraMent').html('<i class="fa-solid fa-check me-1"></i>Mentés');
        $('#sajatOraDiak').val(p.diak);
        $('#sajatOraCim').val(p.cim || p.tantargy || '');
        $('#sajatOraNap').val(String(p.nap || 1));
        $('#sajatOraKezdes').val(p.kezdes || '16:00');
        $('#sajatOraVege').val(p.vege || '17:00');
        $('#sajatOraTerem').val(p.terem || '');
        $('#sajatOraMegjegyzes').val(p.megjegyzes || '');
        $('#sajatOraSzin').val(p.szin || '#6f42c1');
        $('#sajatOraErveny').val('egyedi').trigger('change');
        $('#sajatOraTol').val(p.ervenyes_tol || '');
        $('#sajatOraIg').val(p.ervenyes_ig || '');
        new bootstrap.Modal(document.getElementById('sajatOraModal')).show();
    });

    $(document).on('click', '.btn-sajat-kivetel', function() {
        let id = $(this).data('id');
        let datum = $(this).data('datum');
        if (!confirm(`Csak a(z) ${datum} alkalmat törlöd? A sorozat többi alkalma megmarad.`)) return;
        $.ajax({
            url: `/api/sajat_orarend/${id}/kivetel`,
            type: 'POST',
            contentType: 'application/json',
            data: JSON.stringify({ datum: datum })
        }).done(function() {
            let modal = bootstrap.Modal.getInstance(document.getElementById('detailsModal'));
            if (modal) modal.hide();
            if (orarendCalendar) orarendCalendar.refetchEvents();
        }).fail(function(xhr) {
            alert((xhr.responseJSON && xhr.responseJSON.message) || 'A törlés nem sikerült.');
        });
    });

    $(document).on('click', '.btn-sajat-sorozat', function() {
        let id = $(this).data('id');
        if (!confirm('A teljes sorozatot törlöd (minden alkalommal)?')) return;
        $.ajax({
            url: `/api/sajat_orarend/${id}`,
            type: 'DELETE'
        }).done(function() {
            let modal = bootstrap.Modal.getInstance(document.getElementById('detailsModal'));
            if (modal) modal.hide();
            if (orarendCalendar) orarendCalendar.refetchEvents();
        }).fail(function(xhr) {
            alert((xhr.responseJSON && xhr.responseJSON.message) || 'A törlés nem sikerült.');
        });
    });

    // ── Órarend színek (Kaneo #56) ────────────────────────────────────────
    $('#btnOrarendSzinek').click(function() {
        $('#szinekHiba').addClass('d-none').text('');
        $.getJSON('/api/orarend_szinek', function(res) {
            let box = $('#szinekLista').empty();
            let diakok = res.diakok || [];
            let szinek = res.szinek || {};
            if (!diakok.length) {
                box.append($('<div class="text-muted small">').text('Nincs megjeleníthető diák.'));
            }
            diakok.forEach(function(nev) {
                let row = $('<div class="d-flex align-items-center justify-content-between gap-2 border rounded px-2 py-1">');
                row.append($('<span class="small fw-bold">').text(nev));
                row.append($('<input type="color" class="form-control form-control-color szin-input">')
                    .attr('data-diak', nev)
                    .val(szinek[nev] || '#0d6efd'));
                box.append(row);
            });
            new bootstrap.Modal(document.getElementById('szinekModal')).show();
        });
    });

    $('#btnSzinekMent').click(function() {
        let szinek = {};
        $('#szinekLista .szin-input').each(function() {
            szinek[$(this).attr('data-diak')] = $(this).val();
        });
        $.ajax({
            url: '/api/orarend_szinek',
            type: 'PUT',
            contentType: 'application/json',
            data: JSON.stringify({ szinek: szinek })
        }).done(function() {
            let modal = bootstrap.Modal.getInstance(document.getElementById('szinekModal'));
            if (modal) modal.hide();
            if (orarendCalendar) orarendCalendar.refetchEvents();
        }).fail(function(xhr) {
            $('#szinekHiba').removeClass('d-none').text(
                (xhr.responseJSON && xhr.responseJSON.message) || 'A mentés nem sikerült.');
        });
    });

    $('#esemenyekTable').on('click', '.btn-show-details', function(e) {
        e.stopPropagation();
        const id = Number($(this).data('id'));
        const esemeny = (rawData || []).find(function(x) { return Number(x.id) === id; });
        if (esemeny) {
            reszletekModal(esemeny.esemeny_tipus || 'Esemény részletei',
                           esemenyReszletekSzoveg(esemeny));
        } else {
            reszletekModal('Esemény részletei', $(this).data('text') || '');
        }
    });

    // ── Saját megjegyzések (Kaneo #46) ─────────────────────────────────────
    let kommentCel = { tipus: '', kulcs: '', diak: '', gomb: null };
    let uzenetKommentCel = { kulcs: '', diak: '' };
    let uzenetAktualisId = null;
    let aktualisSajatProps = null;

    function betoltUzenetKommentek() {
        if (!uzenetKommentCel.kulcs) {
            $('#uzenetKommentLista').empty();
            return;
        }
        $.getJSON(`/api/kommentek?cel_tipus=uzenet&cel_kulcs=${encodeURIComponent(uzenetKommentCel.kulcs)}`,
            function (rows) {
                renderKommentLista($('#uzenetKommentLista'), rows || [], 'uzenet');
            });
    }

    function renderKommentLista($container, rows, celTipus) {
        $container.empty();
        if (!rows.length) {
            $container.html('<div class="text-muted small">Még nincs megjegyzés.</div>');
            return;
        }
        rows.forEach(function (k) {
            let idopont = String(k.letrehozva || '').replace('T', ' ');
            let torles = celTipus === 'esemeny'
                ? `<button class="btn btn-sm btn-link text-danger p-0 btn-del-komment" data-id="${k.id}"
                           title="Törlés"><i class="fa-solid fa-trash"></i></button>`
                : '';
            $container.append(`<div class="border rounded p-2 mb-2">
                <div class="d-flex justify-content-between align-items-start gap-2">
                    <div class="small text-muted">${escapeHtml(k.szerzo || 'Szülő')} · ${escapeHtml(idopont)}</div>
                    ${torles}
                </div>
                <div class="small" style="white-space: pre-wrap;">${escapeHtml(k.szoveg || '')}</div>
            </div>`);
        });
    }

    function betoltKommentek() {
        if (!kommentCel.tipus || !kommentCel.kulcs) return;
        $.getJSON(`/api/kommentek?cel_tipus=${encodeURIComponent(kommentCel.tipus)}` +
                  `&cel_kulcs=${encodeURIComponent(kommentCel.kulcs)}`, function (rows) {
            renderKommentLista($('#kommentLista'), rows || [], 'esemeny');
        });
    }

    $('#esemenyekTable').on('click', '.btn-show-komment', function(e) {
        e.stopPropagation();
        let $b = $(this);
        kommentCel = {
            tipus: 'esemeny',
            kulcs: $b.attr('data-kulcs') || '',
            diak: $b.attr('data-diak') || '',
            gomb: $b
        };
        $('#kommentCelInfo').text(kommentCel.diak ? ('Diák: ' + kommentCel.diak) : '');
        $('#kommentUj').val('');
        $('#kommentHiba').addClass('d-none').text('');
        betoltKommentek();
        new bootstrap.Modal(document.getElementById('kommentModal')).show();
    });

    $('#btnKommentMent').click(function() {
        let szoveg = $('#kommentUj').val().trim();
        if (!szoveg) {
            $('#kommentHiba').removeClass('d-none').text('A megjegyzés nem lehet üres.');
            return;
        }
        $.ajax({
            url: '/api/kommentek',
            type: 'POST',
            contentType: 'application/json',
            data: JSON.stringify({
                cel_tipus: kommentCel.tipus,
                cel_kulcs: kommentCel.kulcs,
                diak_nev: kommentCel.diak,
                szoveg: szoveg
            }),
            success: function() {
                $('#kommentUj').val('');
                $('#kommentHiba').addClass('d-none').text('');
                betoltKommentek();
                if (kommentCel.gomb) {
                    let db = (Number(kommentCel.gomb.attr('data-db')) || 0) + 1;
                    kommentCel.gomb.attr('data-db', db);
                    kommentCel.gomb.html('<i class="fa-solid fa-comment-dots"></i> ' + db);
                }
            },
            error: function(xhr) {
                let msg = (xhr.responseJSON && xhr.responseJSON.message) || 'A mentés nem sikerült.';
                $('#kommentHiba').removeClass('d-none').text(msg);
            }
        });
    });

    $(document).on('click', '.btn-del-komment', function() {
        let id = $(this).data('id');
        if (!id || !confirm('Törlöd ezt a megjegyzést?')) return;
        $.ajax({
            url: '/api/kommentek/' + id,
            type: 'DELETE',
            success: function() {
                betoltKommentek();
                if (kommentCel.gomb) {
                    let db = Math.max(0, (Number(kommentCel.gomb.attr('data-db')) || 1) - 1);
                    kommentCel.gomb.attr('data-db', db);
                    kommentCel.gomb.html('<i class="fa-solid fa-comment-dots"></i>' + (db ? ' ' + db : ''));
                }
            }
        });
    });

    $('#esemenyekTable').on('click', '.btn-toggle-kesz', function(e) {
        e.stopPropagation();
        let esemenyId = $(this).data('id');
        let ujKesz = $(this).data('kesz');

        $.ajax({
            url: '/api/esemeny/statusz',
            type: 'POST',
            contentType: 'application/json',
            data: JSON.stringify({
                id: esemenyId,
                kesz: ujKesz
            }),
            success: function(res) {
                if (res.status === 'ok') {
                    let item = rawData.find(x => x.id === esemenyId);
                    if (item) {
                        item.kesz = res.kesz;
                    }
                    applyFilters();
                    if (calendar) {
                        calendar.refetchEvents();
                    }
                }
            }
        });
    });

    function applyFilters() {
        let statusFilter = $('#filterStatus').val();
        let todayNum = getTodayNum();

        let kezdoStr = $('#filterBejKezdoDatum').val();
        let zaroStr = $('#filterBejZaroDatum').val();

        let kezdoNum = kezdoStr ? parseInt(kezdoStr.replace(/-/g, ''), 10) : null;
        let zaroNum = zaroStr ? parseInt(zaroStr.replace(/-/g, ''), 10) : null;

        // Rejtett határidő-szűrő (a dashboard csempéi állítják be, pl. heti határidők).
        let hatKezdoStr = $('#filterHatKezdoDatum').val();
        let hatZaroStr = $('#filterHatZaroDatum').val();
        let hatKezdoNum = hatKezdoStr ? parseInt(hatKezdoStr.replace(/-/g, ''), 10) : null;
        let hatZaroNum = hatZaroStr ? parseInt(hatZaroStr.replace(/-/g, ''), 10) : null;

        let filteredData = rawData.filter(item => {
            if (statusFilter) {
                let hNum = dateToNum(item.hatarido);
                if (!hNum) return false;
                if (statusFilter === 'aktiv' && hNum < todayNum) return false;
                if (statusFilter === 'lejart' && hNum >= todayNum) return false;
            }

            if (kezdoNum || zaroNum) {
                let bejNum = dateToNum(item.bej_datum);
                if (bejNum) {
                    if (kezdoNum && bejNum < kezdoNum) return false;
                    if (zaroNum && bejNum > zaroNum) return false;
                } else {
                    return false;
                }
            }

            if (hatKezdoNum || hatZaroNum) {
                let hNum = dateToNum(item.hatarido);
                if (!hNum) return false;
                if (hatKezdoNum && hNum < hatKezdoNum) return false;
                if (hatZaroNum && hNum > hatZaroNum) return false;
            }

            return true;
        });

        dataTable.clear().rows.add(filteredData).draw();
        kiemelKeresesTalalat();
    }

    // A kereső találatának rövid kiemelése az eseménylistában (Kaneo #102).
    function kiemelKeresesTalalat() {
        if (keresesKiemelId === null) return;
        const id = Number(keresesKiemelId);
        keresesKiemelId = null;
        setTimeout(function() {
            dataTable.rows().every(function() {
                const d = this.data();
                if (!d || Number(d.id) !== id) return;
                const node = this.node();
                $(node).addClass('kereses-kiemel');
                setTimeout(function() { $(node).removeClass('kereses-kiemel'); }, 3200);
            });
        }, 200);
    }

    // A hónap-oszlop csak a hónap neve (a tanév az időszak-feliratban látszik);
    // a teljes "2026. szeptember" a tooltipben van.
    function fmtHonap(yyyymm) {
        const parts = String(yyyymm || '').split('-');
        if (parts.length !== 2) return yyyymm;
        const nevek = ['jan.', 'febr.', 'márc.', 'ápr.', 'máj.', 'jún.',
                       'júl.', 'aug.', 'szept.', 'okt.', 'nov.', 'dec.'];
        const idx = parseInt(parts[1], 10) - 1;
        return nevek[idx] || parts[1];
    }

    function honapNev(yyyymm) {
        const parts = String(yyyymm || '').split('-');
        const nevek = ['január', 'február', 'március', 'április', 'május', 'június',
                       'július', 'augusztus', 'szeptember', 'október', 'november', 'december'];
        if (parts.length !== 2) return yyyymm;
        return `${parts[0]}. ${nevek[parseInt(parts[1], 10) - 1] || parts[1]}`;
    }

    function loadAtlagok(diak, kezdo, zaro) {
        let url = `/api/atlagok?diak=${encodeURIComponent(diak || '')}` +
                  `&kezdo_datum=${encodeURIComponent(kezdo || '')}` +
                  `&zaro_datum=${encodeURIComponent(zaro || '')}` +
                  tanevQueryParam();
        $.getJSON(url, function(res) {
            const honapok = res.honapok || [];
            const tantargyak = res.tantargyak || [];
            const tanev = res.tanev || kivalasztottTanev();

            // Összes tanévnél az átlag nem értelmezhető (Kaneo #40): csak jelzünk.
            if (!tanev) {
                $('#atlagokIdoszak').text('Összes tanév — az átlagok tanévenként értelmezhetők.');
                $('#atlagokOsszes').text('');
                $('#atlagokHeadRow').empty();
                $('#atlagokBody').empty().append(
                    '<tr><td class="text-center text-muted py-2">' +
                    'Az átlagokhoz válassz tanévet a fejlécben.</td></tr>');
                $('#atlagokMobil').empty();
                lastAtlagok = null;
                frissitKalkTantargy(null);
                return;
            }

            let $head = $('#atlagokHeadRow').empty();
            $head.append('<th style="min-width: 130px;">Tantárgy</th>');
            honapok.forEach(function(h) {
                $head.append(`<th class="text-center" style="min-width: 72px;" title="${honapNev(h)}">${fmtHonap(h)}</th>`);
            });
            $head.append('<th class="text-center" style="min-width: 72px;">Összes</th>');
            $head.append('<th class="text-center" style="min-width: 84px;">Trend</th>');
            $head.append('<th class="text-center" style="min-width: 48px;">db</th>');

            // Időszak-felirat: tanév + a kijelölt időszak (a hónap-oszlopoknál már
            // nem ismételjük az évet).
            let idoszakSzoveg = tanEvCimke(tanev);
            if (kezdo || zaro) {
                let fmtD = function(d) {
                    const p = String(d || '').split('-');
                    return p.length === 3 ? `${p[0]}. ${p[1]}. ${p[2]}.` : '';
                };
                const t = [fmtD(kezdo), fmtD(zaro)].filter(Boolean).join(' – ');
                idoszakSzoveg += (idoszakSzoveg ? ' · ' : '') + 'időszak: ' + t;
            }
            $('#atlagokIdoszak').text(idoszakSzoveg);

            let $body = $('#atlagokBody').empty();
            if (!tantargyak.length) {
                $body.append('<tr><td colspan="' + (honapok.length + 4) +
                    '" class="text-center text-muted py-2">Nincs megjeleníthető jegy erre az időszakra.</td></tr>');
            }
            tantargyak.forEach(function(t) {
                let html = `<tr><td class="fw-bold">${escapeHtml(t.tantargy)}</td>`;
                honapok.forEach(function(h) {
                    let m = (t.honapok || {})[h];
                    html += `<td class="text-center">${m && m.atlag !== null ? m.atlag : '-'}</td>`;
                });
                html += `<td class="text-center fw-bold text-primary">${t.osszes && t.osszes.atlag !== null ? t.osszes.atlag : '-'}</td>`;
                html += `<td class="text-center">${trendCella(t)}</td>`;
                html += `<td class="text-center text-muted">${t.osszes ? t.osszes.db : 0}</td></tr>`;
                $body.append(html);
            });
            if (tantargyak.length && res.osszes) {
                // Lábléc: a havi TELJES átlagok (minden tantárgy együtt) + a sarokban a teljes időszak.
                let lab = '<tr class="table-light fw-bold"><td>Hónapok átlaga</td>';
                honapok.forEach(function(h) {
                    let ho = (res.honap_osszes || {})[h] || {};
                    lab += `<td class="text-center">${ho.atlag !== null && ho.atlag !== undefined
                        ? ho.atlag + ' <span class="text-muted fw-normal">(' + (ho.db || 0) + ')</span>'
                        : '-'}</td>`;
                });
                lab += `<td class="text-center text-success">${res.osszes.atlag !== null ? res.osszes.atlag : '-'}` +
                       ` <span class="text-muted fw-normal">(${res.osszes.db})</span></td>`;
                lab += '<td></td></tr>';
                $body.append(lab);
            }

            // Mobil: két bontás, kapcsolóval (a jegyek részletei nem kellenek).
            lastAtlagok = res;
            renderMobilAtlagok(res);
            frissitKalkTantargy(res, diak, kezdo, zaro);
            $('#atlagokOsszes').text(res.osszes && res.osszes.db
                ? `Összesített átlag: ${res.osszes.atlag} (${res.osszes.db} jegy)`
                : '');
        });
    }

    let lastAtlagok = null;
    let atlagNezet = 'havi';

    function renderMobilAtlagok(res) {
        let $mob = $('#atlagokMobil').empty();
        let honapok = res.honapok || [];
        let tantargyak = res.tantargyak || [];
        let ossz = res.osszes || {};

        if (!tantargyak.length) {
            $mob.append('<div class="text-center text-muted small py-2">Nincs megjeleníthető jegy erre az időszakra.</div>');
            return;
        }

        // Mindkét nézet tetején: a teljes (kijelölt időszaki) átlag.
        $mob.append(`<div class="d-flex justify-content-between align-items-center bg-light border rounded p-2 mb-2">
            <span class="fw-bold">Teljes átlag</span>
            <span><strong class="fs-5 text-primary">${ossz.atlag !== null && ossz.atlag !== undefined ? ossz.atlag : '-'}</strong>
            <span class="text-muted small ms-1">(${ossz.db || 0} jegy)</span></span>
        </div>`);

        // 2. nézet: csak tantárgyanként, a teljes időszakra.
        if (atlagNezet === 'tantargy') {
            let sorok = tantargyak.map(function(t) {
                let a = (t.osszes && t.osszes.atlag !== null) ? t.osszes.atlag : '-';
                return `<div class="d-flex justify-content-between border-top py-1">
                    <span>${escapeHtml(t.tantargy)}</span>
                    <span class="text-nowrap"><strong>${a}</strong>
                    <span class="text-muted small">(${t.osszes ? t.osszes.db : 0})</span></span>
                </div>`;
            }).join('');
            $mob.append(`<div class="border rounded p-2">${sorok}</div>`);
            return;
        }

        // 1. nézet: havi bontás — hónap-accordionok, bennük a havi tantárgyi átlagok.
        let honapokHtml = honapok.map(function(h, hi) {
            let ho = (res.honap_osszes || {})[h] || {};
            let hid = 'atlagHo' + hi;
            let sorok = tantargyak.map(function(t) {
                let m = (t.honapok || {})[h];
                if (!m || m.atlag === null) return '';
                return `<div class="d-flex justify-content-between border-top py-1">
                    <span>${escapeHtml(t.tantargy)}</span>
                    <span class="text-nowrap"><strong>${m.atlag}</strong>
                    <span class="text-muted small">(${m.db})</span></span>
                </div>`;
            }).join('');
            return `<div class="accordion-item">
                <h2 class="accordion-header">
                    <button class="accordion-button collapsed py-1 px-2" type="button" data-bs-toggle="collapse" data-bs-target="#${hid}" style="font-size: 0.84rem;">
                        <span class="fw-bold">${honapNev(h)}</span>
                        <span class="badge bg-secondary ms-2">${ho.atlag !== null && ho.atlag !== undefined ? ho.atlag : '-'}</span>
                        <span class="text-muted ms-2" style="font-size: 0.72rem;">${ho.db || 0} jegy</span>
                    </button>
                </h2>
                <div id="${hid}" class="accordion-collapse collapse">
                    <div class="accordion-body p-2">${sorok || '<span class="text-muted small">nincs jegy</span>'}</div>
                </div>
            </div>`;
        }).join('');
        $mob.append(`<div class="accordion">${honapokHtml}</div>`);
    }

    let lastKalkKontekszt = null;

    function frissitKalkTantargy(res, diak, kezdo, zaro) {
        const $sel = $('#kalkTantargy');
        const $eredmeny = $('#kalkEredmeny');
        if (!res) {
            $sel.empty();
            lastKalkKontekszt = null;
            $eredmeny.html('<span class="text-muted">Az átlagokhoz válassz tanévet a fejlécben.</span>');
            $('#kalkJegyek').empty();
            return;
        }
        lastKalkKontekszt = {diak: diak || '', kezdo: kezdo || '', zaro: zaro || ''};
        const tantargyak = (res.tantargyak || []).map(function(t) { return t.tantargy; });
        const elozo = $sel.val();
        $sel.empty();
        $eredmeny.empty();
        $('#kalkJegyek').empty();
        // Alapból ne legyen kiválasztva tantárgy (Kaneo #78): a jegyek listája
        // csak kiválasztás után töltődik be; üres elem is választható.
        $sel.append('<option value="">— Válassz tantárgyat —</option>');
        if (!tantargyak.length) {
            $sel.append('<option value="" disabled>Nincs jegy</option>');
            return;
        }
        tantargyak.forEach(function(t) {
            $sel.append($('<option>').val(t).text(t));
        });
        if (elozo && tantargyak.indexOf(elozo) >= 0) {
            $sel.val(elozo);
            kalkCelBetolt(elozo);
        } else {
            $sel.val('');
        }
    }

    function renderKalkJegyek(jegyek) {
        const $c = $('#kalkJegyek').empty();
        if (!jegyek || !jegyek.length) {
            $c.html('<div class="text-muted small">Ehhez a tantárgyhoz még nincs jegy.</div>');
            return;
        }
        let html = `<div class="small fw-bold text-secondary mb-1">Meglévő jegyek (${jegyek.length})</div>` +
            '<div class="table-responsive"><table class="table table-sm table-striped mb-0" ' +
            'style="font-size: 0.8rem;"><thead class="table-light"><tr>' +
            '<th style="width: 42%;">Dátum</th><th style="width: 33%;">Jegy</th>' +
            '<th style="width: 25%;">Súly</th></tr></thead><tbody>';
        jegyek.forEach(function(j) {
            const nap = j.datum ? fmtIsoToHu(j.datum) : '—';
            const ertek = j.ertek || (j.szam !== undefined ? j.szam : '—');
            html += `<tr><td class="text-nowrap">${escapeHtml(nap)}</td>` +
                    `<td><span class="fw-bold">${escapeHtml(ertek)}</span></td>` +
                    `<td>${j.suly ? j.suly + '%' : '<span class="text-muted">–</span>'}</td></tr>`;
        });
        html += '</tbody></table></div>';
        $c.html(html);
    }

    function kalkVarhatoAdatok() {
        const sulyok = [];
        const varhato = [];
        $('#kalkVarhatoLista .kalk-varhato-sor').each(function() {
            sulyok.push(Number($(this).find('.kalk-suly').val()) || 100);
            const v = $(this).find('.kalk-jegy').val();
            varhato.push(v === '' || v === undefined ? '' : Number(v));
        });
        return {sulyok: sulyok, varhato: varhato};
    }

    function kalkTobbSor() {
        const sulyOpciok = [50, 100, 200].map(function(v) {
            return `<option value="${v}"${v === 100 ? ' selected' : ''}>${v}%</option>`;
        }).join('');
        const jegyOpciok = ['', 1, 2, 3, 4, 5].map(function(v) {
            return `<option value="${v}">${v === '' ? '–' : v}</option>`;
        }).join('');
        return `<div class="d-flex gap-1 mb-1 kalk-varhato-sor">
            <select class="form-select form-select-sm kalk-suly" title="A jegy súlya">${sulyOpciok}</select>
            <select class="form-select form-select-sm kalk-jegy" title="Várható jegy (ha már tudod)">${jegyOpciok}</select>
            <button type="button" class="btn btn-sm btn-outline-danger btn-kalk-sor-torles" title="Sor törlése">×</button>
        </div>`;
    }

    function kalkSorTorlesGombok() {
        const $sorok = $('#kalkVarhatoLista .kalk-varhato-sor');
        $sorok.find('.btn-kalk-sor-torles').toggleClass('d-none', $sorok.length <= 1);
    }

    function kalkCelBetolt(tantargy) {
        if (!lastKalkKontekszt || !tantargy) return;
        $.getJSON(`/api/kalkulator_cel?diak=${encodeURIComponent(lastKalkKontekszt.diak)}` +
                  `&tantargy=${encodeURIComponent(tantargy)}`)
            .done(function(res) {
                if (res && res.cel !== null && res.cel !== undefined) {
                    $('#kalkCel').val(res.cel);
                }
                $('#kalkFelevi').val(res && res.felevi ? String(res.felevi) : '');
                szamolJegyKalkulator();
            })
            .fail(szamolJegyKalkulator);
    }

    function kalkCelMent() {
        const tantargy = $('#kalkTantargy').val();
        if (!tantargy || !lastKalkKontekszt) return;
        $.ajax({
            url: '/api/kalkulator_cel',
            type: 'POST',
            contentType: 'application/json',
            data: JSON.stringify({
                diak: lastKalkKontekszt.diak,
                tantargy: tantargy,
                cel: $('#kalkCel').val(),
                felevi: $('#kalkFelevi').val()
            })
        });
    }

    function szamolJegyKalkulator() {
        if (!lastKalkKontekszt) return;
        const tantargy = $('#kalkTantargy').val();
        if (!tantargy) {
            // Üres kiválasztásnál nincs jegy-lista és nincs eredmény (Kaneo #78).
            $('#kalkEredmeny').empty();
            $('#kalkJegyek').empty();
            return;
        }
        // A kalkulátor mindig a teljes (tanévre szűrt) jegyállományt veszi
        // figyelembe, nem az eseménylista időszak-szűrését (Kaneo #78).
        const adat = kalkVarhatoAdatok();
        const felevi = $('#kalkFelevi').val() || '';
        let url = `/api/jegy_kalkulator?tantargy=${encodeURIComponent(tantargy)}` +
                  `&diak=${encodeURIComponent(lastKalkKontekszt.diak)}` +
                  `&cel=${encodeURIComponent($('#kalkCel').val() || '4.5')}` +
                  `&suly=${encodeURIComponent(adat.sulyok[0] || 100)}` +
                  `&sulyok=${encodeURIComponent(adat.sulyok.join(','))}` +
                  `&varhato=${encodeURIComponent(adat.varhato.join(','))}` +
                  (felevi ? `&felevi=${encodeURIComponent(felevi)}` : '') +
                  tanevQueryParam();
        $('#kalkEredmeny').html('<span class="text-muted">Számolás…</span>');
        $.getJSON(url).done(function(res) {
            let html = `<span class="${res.elerheto ? 'text-success' : 'text-danger'} fw-bold">` +
                       `${escapeHtml(res.uzenet || '')}</span>`;
            if (res.aktualis_atlag !== null && res.aktualis_atlag !== undefined) {
                html += ` <span class="text-muted">— jelenleg ${res.aktualis_atlag} (` +
                        `${res.jegy_db} jegy`;
                if (res.suly_db) html += `, ${res.suly_db} súlyozott`;
                html += ')</span>';
            }
            if (res.szimulalt_atlag !== null && res.szimulalt_atlag !== undefined) {
                html += `<div class="mt-1">A megadott jegyekkel a várható átlag: ` +
                        `<b>${res.szimulalt_atlag}</b>` +
                        (res.cel_teljesul === false
                            ? ' <span class="text-danger">(a cél nem teljesül)</span>' : '') +
                        '</div>';
            }
            if (res.felevi_uzenet) {
                const osztaly = res.felevi_elerheto ? 'text-success' : 'text-danger';
                html += `<div class="mt-1 ${osztaly}">` +
                        `<i class="fa-solid fa-flag-checkered me-1"></i>` +
                        `${escapeHtml(res.felevi_uzenet)}</div>`;
            }
            $('#kalkEredmeny').html(html);
            renderKalkJegyek(res.jegyek || []);
        }).fail(function(xhr) {
            const msg = (xhr.responseJSON && xhr.responseJSON.error) || 'Hiba a számításban.';
            $('#kalkEredmeny').html('<span class="text-danger">' + escapeHtml(msg) + '</span>');
            $('#kalkJegyek').empty();
        });
    }

    $('#btnKalkulal').on('click', function() {
        kalkCelMent();
        szamolJegyKalkulator();
    });
    $('#kalkTantargy').on('change', function() {
        if ($(this).val()) {
            kalkCelBetolt($(this).val());
        } else {
            $('#kalkEredmeny').empty();
            $('#kalkJegyek').empty();
        }
    });
    $('#kalkCel, #kalkFelevi').on('change', function() {
        if (!$('#kalkTantargy').val()) return;
        kalkCelMent();
        szamolJegyKalkulator();
    });
    $('#kalkVarhatoLista').on('change', '.kalk-suly, .kalk-jegy', function() {
        if ($('#kalkTantargy').val()) szamolJegyKalkulator();
    });
    $('#btnKalkVarhatoAdd').on('click', function() {
        $('#kalkVarhatoLista').append(kalkTobbSor());
        kalkSorTorlesGombok();
    });
    $('#kalkVarhatoLista').on('click', '.btn-kalk-sor-torles', function() {
        $(this).closest('.kalk-varhato-sor').remove();
        kalkSorTorlesGombok();
        if ($('#kalkTantargy').val()) szamolJegyKalkulator();
    });

    $('#atlagNezetKapcsolo').on('click', '.btn', function() {
        atlagNezet = $(this).data('nezet') || 'havi';
        $('#atlagNezetKapcsolo .btn').removeClass('active');
        $(this).addClass('active');
        if (lastAtlagok) renderMobilAtlagok(lastAtlagok);
    });

    function loadRewardsData() {
        let diak = $('#rewardFilterDiak').val();
        let kezdo = $('#rewardKezdoDatum').val();
        let zaro = $('#rewardZaroDatum').val();

        if (!diak) {
            $('#rewardContainer').addClass('d-none');
            $('#rewardNoDiakAlert').removeClass('d-none');
            return;
        }
        $('#rewardNoDiakAlert').addClass('d-none');

        let url = `/api/statisztika?diak=${encodeURIComponent(diak)}&kezdo_datum=${encodeURIComponent(kezdo)}&zaro_datum=${encodeURIComponent(zaro)}${tanevQueryParam()}`;

        $.getJSON(url, function(res) {
            if (!res.enabled) {
                $('#rewardContainer').addClass('d-none');
                $('#rewardDisabledAlert').removeClass('d-none');
                return;
            }

            $('#rewardContainer').removeClass('d-none');
            $('#rewardDisabledAlert').addClass('d-none');

            loadAtlagok(diak, kezdo, zaro);

            $('#cntJegy5').text(res.jegy_counts[5] + ' db');
            $('#cntJegy4').text(res.jegy_counts[4] + ' db');
            $('#cntJegy3').text(res.jegy_counts[3] + ' db');
            $('#cntJegy2').text(res.jegy_counts[2] + ' db');
            $('#cntJegy1').text(res.jegy_counts[1] + ' db');

            $('#statAtlag').text(res.atlag);
            if (res.atlag_sulyozott !== null && res.atlag_sulyozott !== undefined) {
                $('#statAtlag').attr('title',
                    'Súlyozott átlag a jegyek súlyszázaléka szerint (' + res.sulyozott_db +
                    ' jegy). Egyszerű átlag: ' + res.atlag_egyszeru);
                $('#statAtlagTip').text('(súlyozott)').attr('title',
                    'Egyszerű átlag: ' + res.atlag_egyszeru);
            } else {
                $('#statAtlag').attr('title', 'Egyszerű átlag (nincs súlyadat)');
                $('#statAtlagTip').text('');
            }
            // Összes tanévnél az átlag nem értelmezhető (Kaneo #40) — a KPI se mutasson számot.
            if (!kivalasztottTanev()) {
                $('#statAtlag').text('–').attr('title',
                    'Összes tanévnél az átlag nem értelmezhető — válassz tanévet a fejlécben.');
                $('#statAtlagTip').text('').attr('title', '');
            }
            $('#statTotalJegy').text(res.jegy_total_count + ' db');

            // A zsebpénz modul kikapcsolt diáknál a statisztika látszik,
            // csak a pénz-kártyát rejtjük el és jelzünk helyette.
            if (res.rewards_enabled === false) {
                $('#cardVegosszegContainer').addClass('d-none');
                $('#rewardsNotEnabledAlert').removeClass('d-none');
            } else {
                $('#cardVegosszegContainer').removeClass('d-none');
                $('#rewardsNotEnabledAlert').addClass('d-none');
            }

            $('#cntDicseret').text(res.counts.dicseret + ' db');
            $('#cntMegrovas').text(res.counts.megrovas + ' db');
            $('#cntLeckeHiany').text(res.counts.lecke_hiany + ' db');
            $('#cntFelszerelesHiany').text(res.counts.felszereles_hiany + ' db');

            let fmtFt = (num) => (num > 0 ? '+' : '') + num.toLocaleString('hu-HU') + ' Ft';

            currentVegosszeg = res.vegosszeg;
            $('#txtVegosszeg').text(fmtFt(res.vegosszeg));

            let $jegyElem = $('#txtJegyOsszeg');
            $jegyElem.text(fmtFt(res.jegy_osszeg));
            if (res.jegy_osszeg > 0) {
                $jegyElem.removeClass().addClass('ms-1 fw-bold text-success');
            } else {
                $jegyElem.removeClass().addClass('ms-1 fw-bold text-dark');
            }

            let $feljElem = $('#txtFeljegyzesOsszeg');
            $feljElem.text(fmtFt(res.feljegyzes_osszeg));
            if (res.feljegyzes_osszeg < 0) {
                $feljElem.removeClass().addClass('ms-1 fw-bold text-danger');
            } else if (res.feljegyzes_osszeg > 0) {
                $feljElem.removeClass().addClass('ms-1 fw-bold text-success');
            } else {
                $feljElem.removeClass().addClass('ms-1 fw-bold text-dark');
            }

            let dText = `${kezdo || 'Kezdet'} - ${zaro || 'Mai nap'}`;
            $('#rewardDiakNevText').text(`${diak} elszámolása (${dText})`);

            let cardBg = $('#cardHeaderBg');
            if (res.vegosszeg >= 0) {
                cardBg.removeClass('balance-card-negative').addClass('balance-card-positive');
            } else {
                cardBg.removeClass('balance-card-positive').addClass('balance-card-negative');
            }

            // TÉTELES TÁBLÁZAT FELTÖLTÉSE
            let $tbody = $('#rewardDetailsTableBody');
            $tbody.empty();

            if (res.teteles_lista && res.teteles_lista.length > 0) {
                res.teteles_lista.forEach(function(item) {
                    let badgeCls = item.tipus === 'Értékelés' ? 'bg-success' : 'bg-warning text-dark';
                    let amountCls = item.osszeg > 0 ? 'text-success fw-bold' : (item.osszeg < 0 ? 'text-danger fw-bold' : 'text-muted');
                    let amountTxt = (item.osszeg > 0 ? '+' : '') + item.osszeg.toLocaleString('hu-HU') + ' Ft';

                    let rowHtml = `<tr>
                        <td>${item.datum}</td>
                        <td><span class="badge ${badgeCls}">${item.tipus}</span></td>
                        <td><strong>${item.megnevezes}</strong></td>
                        <td class="text-muted cell-truncate" style="max-width: 300px;" title="${item.reszletek}">${item.reszletek || '-'}</td>
                        <td class="text-end ${amountCls}">${amountTxt}</td>
                    </tr>`;
                    $tbody.append(rowHtml);
                });
            } else {
                $tbody.html('<tr><td colspan="5" class="text-center text-muted py-2">Nincs megjeleníthető tétel erre az időszakra.</td></tr>');
            }

            $('#chkKifizetve').prop('checked', res.kifizetve);
            updateKifizetveLabel(res.kifizetve);
        });
    }

    function updateKifizetveLabel(isPaid) {
        if (isPaid) {
            $('#lblKifizetve').html('🟢 <strong>KIFIZETVE</strong> erre az időszakra').addClass('text-success');
        } else {
            $('#lblKifizetve').html('⚪ Zsebpénz kifizetése erre az időszakra').removeClass('text-success');
        }
    }

    $('#chkKifizetve').change(function() {
        let isChecked = $(this).is(':checked');
        let diak = $('#rewardFilterDiak').val();
        let kezdo = $('#rewardKezdoDatum').val();
        let zaro = $('#rewardZaroDatum').val();

        if (!diak || !kezdo || !zaro) return;

        updateKifizetveLabel(isChecked);

        $.ajax({
            url: '/api/kifizetes',
            type: 'POST',
            contentType: 'application/json',
            data: JSON.stringify({
                diak: diak,
                kezdo_datum: kezdo,
                zaro_datum: zaro,
                kifizetve: isChecked,
                osszeg: currentVegosszeg
            })
        });
    });

    $('#btnQuickThisMonth').click(function() {
        let now = new Date();
        let y = now.getFullYear();
        let m = now.getMonth();
        let firstDay = new Date(y, m, 1);
        let lastDay = new Date(y, m + 1, 0);
        let r = clampTanevRange(fmtDate(firstDay), fmtDate(lastDay));

        $('#rewardKezdoDatum').val(r.kezdo);
        $('#rewardZaroDatum').val(r.zaro);
        loadRewardsData();
    });

    $('#btnQuickLastMonth').click(function() {
        let now = new Date();
        let y = now.getFullYear();
        let m = now.getMonth() - 1;
        if (m < 0) { m = 11; y--; }
        let firstDay = new Date(y, m, 1);
        let lastDay = new Date(y, m + 1, 0);
        let r = clampTanevRange(fmtDate(firstDay), fmtDate(lastDay));

        $('#rewardKezdoDatum').val(r.kezdo);
        $('#rewardZaroDatum').val(r.zaro);
        loadRewardsData();
    });

    // Excel export: az egyenleg tételei (a pénzügyi rendezettség jelölésével).
    // period = a felső időszakválasztó; tanev = a fejlécben kiválasztott teljes
    // tanév; all = minden tanév (teljes előzmény).
    function kifizetesXlsxUrl(mode) {
        let diak = $('#rewardFilterDiak').val() || '';
        let url = '/api/kifizetesek/export.xlsx?diak=' + encodeURIComponent(diak);
        let tanev = kivalasztottTanev();
        if (mode === 'period') {
            url += '&kezdo_datum=' + encodeURIComponent($('#rewardKezdoDatum').val() || '')
                 + '&zaro_datum=' + encodeURIComponent($('#rewardZaroDatum').val() || '');
            if (tanev) url += '&tanev=' + encodeURIComponent(tanev);
        } else if (mode === 'tanev') {
            url += '&tanev=' + encodeURIComponent(tanev || 'all');
        } else {
            url += '&tanev=all';
        }
        return url;
    }

    $('#btnExportKifizetesXlsx').click(function(e) {
        e.preventDefault();
        window.location.href = kifizetesXlsxUrl('period');
    });

    $('.dropdown-menu [data-export]').click(function(e) {
        e.preventDefault();
        window.location.href = kifizetesXlsxUrl($(this).data('export'));
    });

    // ── Tanév-választó (Kaneo #40, 5. fázis) ────────────────────────────────
    // A kiválasztott tanév az eseményeket, a hiányzásokat, az átlagokat és a
    // zsebpénzt szűri. Az üzenetek és az órarend tudatosan tanév-független.
    let tanevAktualis = '';
    let tanevLista = [];
    let tanevHatarok = {};
    let tanevAllapot = {};

    function tanEvCimke(tanev) {
        return tanev + '. tanév';
    }

    function kivalasztottTanev() {
        return $('#tanevValaszto').val() || '';
    }

    // Üres választás = összes tanév (az API-ban ez a visszafelé kompatibilis alap).
    function tanevQueryParam() {
        let t = kivalasztottTanev();
        return `&tanev=${encodeURIComponent(t || 'all')}`;
    }

    // ── Tanév-állapot (Kaneo #43) ──────────────────────────────────────────
    // A zárás/nyitás automatikus: a KRÉTA TanevUid változásakor a backend
    // lezárja a nyitott tanévet és megnyitja az újat (adatlekérés nélkül).
    function updateTanevAllapotBadge() {
        let t = kivalasztottTanev() || tanevAktualis || '';
        let st = t ? (tanevAllapot[t] || null) : null;
        let $b = $('#tanevAllapotBadge');
        if (!st) {
            $b.addClass('d-none').text('');
            return;
        }
        if (st.allapot === 'lezart') {
            let datum = (st.lezarva_at || '').slice(0, 10);
            $b.removeClass('bg-success-subtle text-success-emphasis border-success-subtle')
              .addClass('bg-secondary-subtle text-secondary-emphasis border-secondary-subtle')
              .text('lezárt' + (datum ? ' · ' + datum : ''))
              .removeClass('d-none');
        } else {
            $b.removeClass('bg-secondary-subtle text-secondary-emphasis border-secondary-subtle')
              .addClass('bg-success-subtle text-success-emphasis border-success-subtle')
              .text('nyitott')
              .removeClass('d-none');
        }
    }

    function reloadTanevFuggoNezetek() {
        // A loadData() maga is frissíti a dashboardot és a zsebpénzt.
        loadData();
        loadHianyzasok();
    }

    // ── Dátumválasztók a kiválasztott tanévhez igazítva (Kaneo #53) ────────
    const TANEV_DATUM_MEZOK = ['#filterBejKezdoDatum', '#filterBejZaroDatum',
                               '#rewardKezdoDatum', '#rewardZaroDatum'];

    function aktualisTanevHatar() {
        let t = kivalasztottTanev();
        let h = t ? tanevHatarok[t] : null;
        return (h && h.kezdo && h.zaro) ? h : null;
    }

    function applyTanevDateLimits() {
        let h = aktualisTanevHatar();
        TANEV_DATUM_MEZOK.forEach(function (sel) {
            let $i = $(sel);
            if (h) {
                $i.attr('min', h.kezdo).attr('max', h.zaro);
                let v = $i.val();
                if (v && (v < h.kezdo || v > h.zaro)) $i.val('');
            } else {
                $i.removeAttr('min').removeAttr('max');
            }
        });
        // A hiányzások hónapválasztója (input type=month) ugyanígy.
        let $h = $('#hianyzasHonap');
        if (h) {
            let minH = h.kezdo.slice(0, 7), maxH = h.zaro.slice(0, 7);
            $h.attr('min', minH).attr('max', maxH);
            let v = $h.val();
            if (v && (v < minH || v > maxH)) $h.val('');
        } else {
            $h.removeAttr('min').removeAttr('max');
        }
    }

    // A gyorsgombok által adott intervallumot a tanév határai közé vágja.
    function clampTanevRange(kezdo, zaro) {
        let h = aktualisTanevHatar();
        if (!h) return { kezdo: kezdo, zaro: zaro };
        if (kezdo && kezdo < h.kezdo) kezdo = h.kezdo;
        if (zaro && zaro > h.zaro) zaro = h.zaro;
        if (kezdo && zaro && kezdo > zaro) return { kezdo: '', zaro: '' };
        return { kezdo: kezdo, zaro: zaro };
    }

    // Ha a böngésző engedné a tanéven kívüli értéket (pl. begépelve), a change
    // esemény törli (Kaneo #53).
    $(document).on('change', '#filterBejKezdoDatum, #filterBejZaroDatum, ' +
                             '#rewardKezdoDatum, #rewardZaroDatum', function () {
        let h = aktualisTanevHatar();
        if (!h) return;
        let v = $(this).val();
        if (v && (v < h.kezdo || v > h.zaro)) $(this).val('');
    });
    $(document).on('change', '#hianyzasHonap', function () {
        let h = aktualisTanevHatar();
        if (!h) return;
        let v = $(this).val();
        if (v && (v < h.kezdo.slice(0, 7) || v > h.zaro.slice(0, 7))) $(this).val('');
    });

    function betoltTanevek(megtartValasztas) {
        $.getJSON('/api/tanevek', function (res) {
            let korabbi = $('#tanevValaszto').val();
            tanevAktualis = (res && res.aktualis) || '';
            tanevLista = (res && res.tanevek) || [];
            tanevHatarok = (res && res.hatarok) || {};
            tanevAllapot = (res && res.allapot) || {};
            let $sel = $('#tanevValaszto').empty();
            $sel.append('<option value="">Összes tanév</option>');
            tanevLista.forEach(function (t) {
                let allapot = (tanevAllapot[t] || {}).allapot || '';
                let jelzes = t === tanevAktualis ? ' (aktuális)'
                            : (allapot === 'lezart' ? ' (lezárt)' : '');
                $sel.append(`<option value="${escapeHtml(t)}">${escapeHtml(t)}${jelzes}</option>`);
            });
            // Tanévváltás után (vagy üres DB-nél) az aktuális tanév még nem
            // szerepel a listában — ilyenkor is választható legyen.
            if (tanevAktualis && tanevLista.indexOf(tanevAktualis) === -1) {
                $sel.append(`<option value="${escapeHtml(tanevAktualis)}">` +
                            `${escapeHtml(tanevAktualis)} (aktuális)</option>`);
            }
            // Szinkron utáni újratöltésnél tartsuk meg a felhasználó választását.
            let cel = tanevAktualis || '';
            if (megtartValasztas && korabbi !== null && korabbi !== undefined) cel = korabbi;
            $sel.val(cel);
            applyTanevDateLimits();
            updateTanevAllapotBadge();
            reloadTanevFuggoNezetek();
        }).fail(function () {
            reloadTanevFuggoNezetek();
        });
    }

    $('#tanevValaszto').change(function () {
        applyTanevDateLimits();
        updateTanevAllapotBadge();
        reloadTanevFuggoNezetek();
    });

    function loadData() {
        let diak = $('#filterDiak').val();
        let tipus = $('#filterTipus').val();
        let tantargy = $('#filterTantargy').val();

        $.getJSON(`/api/esemenyek?diak=${encodeURIComponent(diak)}&tipus=${encodeURIComponent(tipus)}&tantargy=${encodeURIComponent(tantargy)}${tanevQueryParam()}`, function(data) {
            rawData = data;
            applyFilters();

            // Üres tanév: segítsünk megtalálni az adatot.
            let hint = $('#esemenyTanevHint');
            if (!data.length && kivalasztottTanev()) {
                hint.removeClass('d-none').html(
                    `<i class="fa-solid fa-circle-info me-1"></i>A(z) <b>${escapeHtml(kivalasztottTanev())}. tanévben</b> ` +
                    'nincs megjeleníthető esemény. Válaszd az <b>Összes tanévet</b> a fejlécben.');
            } else {
                hint.addClass('d-none');
            }
        });

        $.getJSON(`/api/uzenetek?diak=${encodeURIComponent(diak)}`, function(data) {
            rawUzenetek = data;
            updateUzenetOlvasatlanBadge();
            uzenetekTable.clear().rows.add(data).draw();
        });

        // A dashboard a saját, szűrő nélküli adatát kéri (Kaneo #76) — így az
        // eseménylista filtrációja nem tudja kiüríteni a csempéket/feedet.
        loadDashboardData();
        loadTrendFigyelmeztetes();
        loadMaNezet();

        if ($('#rewards-tab').length > 0) {
            loadRewardsData();
        }
        loadDashboardSummary();
    }

    // ── Áttekintés (dashboard) ─────────────────────────────────────────────
    // A dashboard a saját, SZŰRŐK NÉLKÜLI adatforrását használja (Kaneo #76):
    // az eseménylistás filtráció (tipus/tantargy) nem nyomhatta el a csempéken
    // és a feeden az adatokat — csak a gyermek- és tanév-szűrés számít itt.
    let dashRaw = { esemenyek: [], uzenetek: [] };

    function loadDashboardData() {
        let diak = $('#filterDiak').val() || '';
        $.getJSON(`/api/esemenyek?diak=${encodeURIComponent(diak)}${tanevQueryParam()}`, function (data) {
            dashRaw.esemenyek = data || [];
            updateDashboard();
            renderDashboardFeeds();
        });
        $.getJSON(`/api/uzenetek?diak=${encodeURIComponent(diak)}`, function (data) {
            dashRaw.uzenetek = data || [];
            updateDashboard();
        });
    }

    function fmtFtShort(num) {
        let n = Number(num) || 0;
        return (n > 0 ? '+' : '') + n.toLocaleString('hu-HU') + ' Ft';
    }

    function dateToNumObj(d) {
        return parseInt(fmtDate(d).replace(/-/g, ''), 10);
    }

    // KPI-érték + szín: 0 esetén "inaktív" (szürke/zöld), különben az aktív szín.
    function setKpiSzam(sel, szoveg, aktivOsztaly, nullaOsztaly, ertek) {
        let $el = $(sel);
        $el.text(szoveg);
        $el.removeClass('text-primary text-success text-info text-warning text-danger text-secondary');
        let n = (ertek === undefined) ? Number(szoveg) : Number(ertek);
        $el.addClass(n === 0 ? (nullaOsztaly || 'text-secondary') : aktivOsztaly);
    }

    function updateDashboard() {
        let today = new Date();
        // Következő 10 nap: házi feladatok és számonkérések külön kártyán.
        let limit = new Date(today.getFullYear(), today.getMonth(), today.getDate() + 10);
        let todayNum = dateToNumObj(today);
        let limitNum = dateToNumObj(limit);

        let hazi = 0;
        let szamonkeres = 0;
        dashRaw.esemenyek.forEach(function (item) {
            if (item.esemeny_tipus !== 'Házi feladat' &&
                item.esemeny_tipus !== 'Bejelentett számonkérés') return;
            let hNum = dateToNum(item.hatarido);
            if (!hNum || hNum < todayNum || hNum > limitNum) return;
            if (item.esemeny_tipus === 'Házi feladat') hazi++; else szamonkeres++;
        });
        setKpiSzam('#tileHaziSzam', hazi, 'text-primary');
        setKpiSzam('#tileSzamSzam', szamonkeres, 'text-warning');

        // Egységes ablak: jegyek és üzenetek is az elmúlt 10 napban.
        let from10 = new Date(today.getFullYear(), today.getMonth(), today.getDate() - 10);
        let f10Num = dateToNumObj(from10);

        let ujJegy = 0;
        dashRaw.esemenyek.forEach(function (item) {
            if (item.esemeny_tipus !== 'Értékelés') return;
            let d = dateToNum(item.letrehozva || item.bej_datum);
            if (d && d >= f10Num) ujJegy++;
        });
        setKpiSzam('#tileUjJegyekSzam', ujJegy, 'text-success');

        let ujUzenet = 0;
        dashRaw.uzenetek.forEach(function (msg) {
            let d = dateToNum(msg.letrehozva || msg.idopont);
            if (d && d >= f10Num) ujUzenet++;
        });
        setKpiSzam('#tileUjUzenetekSzam', ujUzenet, 'text-info');
    }

    function renderDiakCards(diakok) {
        let $c = $('#dashboardDiakCards').empty();
        // Összes tanévnél nincs értelmes tanulmányi átlag (Kaneo #40) — a
        // magyarázat egyszer, a szakasz fejlécében van, nem minden kártyán.
        const tanev = kivalasztottTanev();
        $('#diakOsszesitoInfo')
            .text(tanev ? `súlyozott tanulmányi átlag · ${tanev}. tanév`
                        : 'az átlaghoz válassz tanévet a fejlécben')
            .attr('title', 'A tanulmányi átlag a jegyek KRÉTA súlyszázaléka szerint súlyozva, a kiválasztott tanévben.');
        if (!diakok || !diakok.length) {
            $c.append('<div class="col-12 text-muted small">Nincs megjeleníthető diák.</div>');
            return;
        }
        diakok.forEach(function (d) {
            let vanAtlag = !!tanev && d.atlag !== null && d.atlag !== undefined;
            let atlag = vanAtlag ? d.atlag : '-';
            let c = avatarColor(d.diak);
            let monogram = avatarInitials(d.diak);
            let nev = escapeHtml(d.diak);
            let kattinthato = vanAtlag;
            let kartyaAttr = kattinthato
                ? ` role="button" tabindex="0" data-diak="${nev}"` +
                  ` title="Ugrás a statisztikára – havi tantárgyi átlagok"` +
                  ` aria-label="Ugrás a statisztikára: ${nev}"`
                : '';
            let penz;
            if (d.rewards_enabled) {
                penz = `<span class="small text-nowrap">Kifizetetlen: <strong>${fmtFtShort(d.hatralevo)}</strong>` +
                    (d.kifizetve_osszeg
                        ? ` <span class="text-muted">(már kifizetve: ${Math.abs(d.kifizetve_osszeg).toLocaleString('hu-HU')} Ft)</span>`
                        : '') +
                    `</span>`;
            } else {
                penz = '<i class="fa-solid fa-ban text-secondary" title="zsebpénz modul kikapcsolva"></i>';
            }
            $c.append(`<div class="col">
                <div class="card card-stat bg-white p-2 h-100${kattinthato ? ' diak-atlag-kartya' : ''}"${kartyaAttr}>
                    <div class="d-flex align-items-center gap-2">
                        <span class="avatar" style="background:${c[0]};color:${c[1]}" title="${nev}">${monogram}</span>
                        <div class="fw-bold text-truncate">${nev}</div>
                        <span class="badge bg-light text-secondary ms-auto"
                              title="${d.jegy_db} jegy a kiválasztott tanévben">${d.jegy_db} jegy</span>
                    </div>
                    <div class="d-flex align-items-baseline gap-2 flex-wrap mt-1">
                        <div class="fs-3 fw-bold lh-1 ${vanAtlag ? 'text-primary' : 'text-secondary'}">${atlag}</div>
                        ${kattinthato ? '<i class="fa-solid fa-chart-line text-primary small" aria-hidden="true"></i>' : ''}
                        ${penz}
                    </div>
                </div>
            </div>`);
        });
    }

    function openStatisztikaForDiak(diak) {
        diak = String(diak || '');
        if (!diak) return;
        const h = aktualisTanevHatar();
        $('#rewardFilterDiak').val(diak);
        if (h) {
            $('#rewardKezdoDatum').val(h.kezdo);
            $('#rewardZaroDatum').val(h.zaro);
        }
        $('#riportDiak').val(diak);
        showMainTab('rewards-tab');
        setTimeout(function() {
            const collapse = document.getElementById('atlagokCollapse');
            if (collapse && !collapse.classList.contains('show')) {
                bootstrap.Collapse.getOrCreateInstance(collapse, {toggle: false}).show();
            }
            const card = document.getElementById('atlagokCard');
            if (card) card.scrollIntoView({behavior: 'smooth', block: 'start'});
        }, 300);
    }

    function bejegyzesKategoria(tipus) {
        let t = String(tipus || '').toLowerCase();
        if (t.includes('dicsér')) return { cimke: 'Dicséret', osztaly: 'bg-success' };
        if (t.includes('felszerelés')) return { cimke: 'Felszereléshiány', osztaly: 'bg-secondary' };
        if (t.includes('lecke') || t.includes('házi')) return { cimke: 'Leckehiány', osztaly: 'bg-warning text-dark' };
        if (t.includes('figyelmeztet') || t.includes('intő') || t.includes('megrov')
            || t.includes('rovás') || t.includes('fekete')) {
            return { cimke: 'Figyelmeztetés', osztaly: 'bg-danger' };
        }
        return { cimke: (tipus && tipus !== '-') ? tipus : 'Bejegyzés', osztaly: 'bg-secondary' };
    }

    function jegySzin(szam) {
        let n = Number(szam);
        return 'jegy-' + (n >= 1 && n <= 5 ? n : 3);
    }

    // Dashboard alsó sáv: utolsó 10 feljegyzés + utolsó 10 jegy (a rawData a
    // kiválasztott gyermekre/tanévre már szűrve van).
    function renderDashboardFeeds() {
        let feljegyzesek = dashRaw.esemenyek
            .filter(function (x) { return x.esemeny_tipus === 'Feljegyzés'; })
            .sort(function (a, b) {
                return (dateToNum(b.letrehozva || b.bej_datum) || 0)
                     - (dateToNum(a.letrehozva || a.bej_datum) || 0);
            })
            .slice(0, 10);
        let $f = $('#dashFigyelemLista').empty();
        if (!feljegyzesek.length) {
            $f.append('<div class="list-group-item text-muted small px-2 py-2">Nincs legutóbbi bejegyzés.</div>');
        }
        feljegyzesek.forEach(function (x) {
            let k = bejegyzesKategoria(x.tipus);
            let leiras = (x.tartalom && x.tartalom !== '-') ? x.tartalom
                       : ((x.cim && x.cim !== '-') ? x.cim : (x.tema || ''));
            $f.append(`<div class="list-group-item px-2 py-1">
                <div class="d-flex align-items-center gap-2">
                    <span class="badge ${k.osztaly}">${escapeHtml(k.cimke)}</span>
                    <span class="fw-bold small text-truncate">${escapeHtml(x.diak_nev || '')}</span>
                    <span class="text-muted ms-auto text-nowrap" style="font-size: .72rem;">${escapeHtml(x.bej_datum || '')}</span>
                </div>
                <div class="text-muted text-truncate" style="font-size: .72rem;"
                     title="${escapeHtml(leiras)}">${escapeHtml(leiras || '-')}</div>
            </div>`);
        });

        let jegyek = dashRaw.esemenyek
            .filter(function (x) {
                return x.esemeny_tipus === 'Értékelés' && Number(x.szam_ertek) >= 1;
            })
            .sort(function (a, b) {
                return (dateToNum(b.letrehozva || b.bej_datum) || 0)
                     - (dateToNum(a.letrehozva || a.bej_datum) || 0);
            })
            .slice(0, 10);
        let $j = $('#dashJegyLista').empty();
        if (!jegyek.length) {
            $j.append('<div class="list-group-item text-muted small px-2 py-2">Nincs legutóbbi jegy.</div>');
        }
        jegyek.forEach(function (x) {
            let temak = [x.tantargy, x.tema].filter(function (v) {
                return v && v !== '-';
            }).join(' · ');
            $j.append(`<div class="list-group-item px-2 py-1 d-flex align-items-center gap-2">
                <span class="jegy-kor ${jegySzin(x.szam_ertek)}">${escapeHtml(String(x.szam_ertek))}</span>
                <div class="feed-main">
                    <div class="fw-bold small text-truncate">${escapeHtml(x.diak_nev || '')}</div>
                    <div class="text-muted text-truncate" style="font-size: .72rem;"
                         title="${escapeHtml(temak)}">${escapeHtml(temak || '-')}</div>
                </div>
                <span class="text-muted ms-auto text-nowrap" style="font-size: .72rem;">${escapeHtml(x.bej_datum || '')}</span>
            </div>`);
        });
    }

    function loadDashboardSummary() {
        let diak = $('#filterDiak').val() || '';
        $.getJSON(`/api/dashboard?diak=${encodeURIComponent(diak)}${tanevQueryParam()}`, function (res) {
            if (!res || !res.enabled) return;
            let iga = Number(res.igazolatlan_ora) || 0;
            setKpiSzam('#tileIgazolatlanSzam', iga + ' óra', 'text-danger', 'text-success', iga);

            if ($('#rewards-tab').length === 0) {
                setKpiSzam('#tileZsebpenzSzam', '-', 'text-secondary', 'text-secondary', 0);
            } else {
                let hatralevo = Number(res.osszes_hatralevo) || 0;
                setKpiSzam('#tileZsebpenzSzam', fmtFtShort(hatralevo),
                           hatralevo > 0 ? 'text-warning-emphasis' : 'text-danger',
                           'text-success', hatralevo);
            }
            renderDiakCards(res.diakok || []);
        });
    }

    $('#atlagokCollapse').on('show.bs.collapse', function () {
        $('#iconAtlagok').removeClass('fa-chevron-down').addClass('fa-chevron-up');
    }).on('hide.bs.collapse', function () {
        $('#iconAtlagok').removeClass('fa-chevron-up').addClass('fa-chevron-down');
    });

    function showMainTab(tabId) {
        let el = document.getElementById(tabId);
        if (el) bootstrap.Tab.getOrCreateInstance(el).show();
    }

    function setDiakFilter(value) {
        let v = value || '';
        $('#filterDiak').val(v).trigger('change');
        $('.chip-diak').removeClass('active').filter(function () {
            return ($(this).data('diak') || '') === v;
        }).addClass('active');
    }

    function goToEvents(opts) {
        opts = opts || {};
        if (opts.diak !== undefined) $('#filterDiak').val(opts.diak || '');
        if (opts.tipus !== undefined) $('#filterTipus').val(opts.tipus || '');
        if (opts.tantargy !== undefined) $('#filterTantargy').val(opts.tantargy || '');
        if (opts.status !== undefined) $('#filterStatus').val(opts.status || '');
        if (opts.kezdo !== undefined) $('#filterBejKezdoDatum').val(opts.kezdo || '');
        if (opts.zaro !== undefined) $('#filterBejZaroDatum').val(opts.zaro || '');
        if (opts.hatKezdo !== undefined) $('#filterHatKezdoDatum').val(opts.hatKezdo || '');
        if (opts.hatZaro !== undefined) $('#filterHatZaroDatum').val(opts.hatZaro || '');
        showMainTab('esemenyek-tab');
        loadData();   // a szerveroldali (diák/típus/tantárgy) szűrő miatt
    }

    // ── Ütemező visszajelzése a fejlécben ───────────────────────────────────
    function schedulerAlwaysOn(sched) {
        return sched.start_hour === sched.end_hour
            || (sched.start_hour === 0 && sched.end_hour === 24);
    }

    function schedulerWindowHtml(sched) {
        if (schedulerAlwaysOn(sched)) {
            return 'időablak: <b>egész nap</b>';
        }
        const pad = h => String(h).padStart(2, '0') + ':00';
        return `időablak: <b>${pad(sched.start_hour)}–${pad(sched.end_hour)}</b>`;
    }

    function schedulerIntervalText(sched) {
        return schedulerAlwaysOn(sched)
            ? `(egész nap, ${sched.interval_minutes} percenként)`
            : `(az időszakban ${sched.interval_minutes} percenként)`;
    }

    function schedStatusHtml(st, failed) {
        const failedTxt = (failed && failed.length) ? String(failed.join(', ')) : '';
        const titleAttr = failedTxt ? ` title="Nem frissült: ${failedTxt}"` : '';
        if (st === 'done') return '<span class="text-success fw-bold">sikeres</span>';
        if (st === 'done_with_errors') return `<span class="text-warning fw-bold"${titleAttr}>részleges hiba</span>`;
        if (st === 'running') return '<span class="text-primary">folyamatban...</span>';
        if (st === 'stopped') return '<span class="text-secondary">leállítva</span>';
        if (st === 'interrupted') return '<span class="text-warning">megszakadt</span>';
        if (st === 'error') return '<span class="text-danger fw-bold">hiba</span>';
        return st ? `<span class="text-secondary">${st}</span>` : '';
    }

    // Szinkron-szünet sáv (Kaneo #145): felül, kiemelve, ha aktív intervallum van.
    function renderSzunetBanner(szunet) {
        const box = $('#szunetBanner');
        const active = szunet && szunet.active;
        if (!active) {
            box.addClass('d-none').empty();
            return;
        }
        const huDatum = function(iso) {
            const d = new Date(String(iso) + 'T00:00:00');
            if (isNaN(d.getTime())) return iso;
            return `${d.getFullYear()}. ${String(d.getMonth() + 1).padStart(2, '0')}. ` +
                   `${String(d.getDate()).padStart(2, '0')}.`;
        };
        const napi = active.napi_sync
            ? `<div class="szunet-daily"><i class="fa-solid fa-shield-halved"></i> ` +
              `<span class="szunet-daily-long">Napi egy biztonsági szinkron bekapcsolva, ekkor: ` +
              `<b>${escapeHtml(active.napi_ido)}</b></span>` +
              `<span class="szunet-daily-short">Biztonsági szinkron: ` +
              `<b>${escapeHtml(active.napi_ido)}</b></span></div>`
            : '<div class="szunet-daily"><i class="fa-solid fa-ban"></i>' +
              '<span class="szunet-daily-long">Napi biztonsági szinkron nincs bekapcsolva</span>' +
              '<span class="szunet-daily-short">Biztonsági szinkron: kikapcsolva</span></div>';
        box.removeClass('d-none').html(
            '<div class="szunet-icon"><i class="fa-solid fa-circle-pause"></i></div>' +
            '<div class="szunet-body">' +
            '<div class="szunet-head">' +
            '<div class="szunet-title"><span class="badge me-1">SZÜNET</span>' +
            '<span class="szunet-title-text">Szüneti szinkron üzemmód</span></div>' +
            `<div class="szunet-when"><b>${escapeHtml(active.nev)}</b> ` +
            `<span class="szunet-dates">(${huDatum(active.kezdo)} – ${huDatum(active.vege)})</span></div>` +
            '</div>' +
            '<div class="szunet-meta">A beállított rendszeres szinkron szüneti üzemmódban működik.</div>' +
            napi + '</div>');
    }

    function refreshSchedulerInfo(sched) {
        if (!sched || typeof sched !== 'object') {
            $.getJSON('/api/scheduler/status', function(res) { refreshSchedulerInfo(res); });
            return;
        }
        $('#schedulerInfo').removeClass('d-none');
        renderSzunetBanner(sched.szunet);
        const badge = $('#schedulerState');

        // 1) Be van-e kapcsolva az ütemező?
        const stateHtml = sched.enabled
            ? '<i class="fa-solid fa-clock me-1"></i>Ütemező: BE'
            : '<i class="fa-solid fa-clock me-1"></i>Ütemező: KI';
        badge.removeClass('bg-secondary bg-success')
             .addClass(sched.enabled ? 'bg-success' : 'bg-secondary')
             .html(stateHtml);

        // 2) Következő futás / épp futó szinkron
        let nextHtml;
        let nextModalHtml;
        if (!sched.enabled) {
            nextHtml = nextModalHtml = '<span class="text-secondary">automatikus szinkron kikapcsolva</span>';
        } else if (sched.running) {
            const runTxt = sched.trigger === 'scheduled'
                ? '<span class="text-success fw-bold">ütemezett szinkron fut...</span>'
                : '<span class="text-primary fw-bold">kézi szinkron fut...</span>';
            nextHtml = runTxt + ` <span class="text-secondary">${schedulerIntervalText(sched)}</span>`;
            nextModalHtml = runTxt;
        } else if (sched.szunet && sched.szunet.active) {
            const a = sched.szunet.active;
            const daily = a.napi_sync
                ? `napi szinkron: <b>${escapeHtml(a.napi_ido)}</b>`
                : 'nincs automatikus szinkron';
            nextHtml = nextModalHtml =
                `<span class="text-warning fw-bold">szünetel: ${escapeHtml(a.nev)}</span> ` +
                `<span class="text-secondary">${daily}</span>`;
        } else {
            const when = formatSchedTime(sched.next_run_iso);
            if (when) {
                const overdue = new Date(String(sched.next_run_iso).replace(' ', 'T')) <= new Date();
                const base = `következő: <b>${when}</b>`
                           + (overdue ? ' <span class="text-warning">(hamarosan)</span>' : '');
                nextHtml = base + ` <span class="text-secondary">${schedulerIntervalText(sched)}</span>`;
                nextModalHtml = base;
            } else {
                nextHtml = nextModalHtml = `<span class="text-secondary">${schedulerIntervalText(sched)}</span>`;
            }
        }
        $('#schedulerWindowText').html(schedulerWindowHtml(sched));
        $('#schedulerNextText').html(nextHtml);

        // 3) Utolsó frissítés ÉS utolsó automatikus futás — mindkettő saját eredménnyel
        let lastHtml;
        if (!sched.last_run) {
            lastHtml = 'Utolsó frissítés: <span class="text-secondary">még nem volt</span>';
        } else {
            const parts = [];

            const when = formatSchedTime(sched.last_run) || sched.last_run;
            const trig = sched.last_trigger === 'scheduled'
                ? '<span class="badge bg-primary">automatikus</span>'
                : '<span class="badge bg-warning text-dark">kézi</span>';
            const st = schedStatusHtml(sched.running ? 'running' : sched.last_status, sched.last_failed_students);
            parts.push(`<span class="text-nowrap">Utolsó frissítés: <b>${when}</b> ${trig}${st ? ' &middot; ' + st : ''}</span>`);

            // Ha az utolsó futás kézi volt, az ütemező ciklusának alapja külön sor.
            if (sched.last_trigger !== 'scheduled' && sched.last_scheduled_run) {
                const aw = formatSchedTime(sched.last_scheduled_run) || sched.last_scheduled_run;
                const ast = schedStatusHtml(sched.last_scheduled_status, sched.last_scheduled_failed_students);
                parts.push(`<span class="text-nowrap">Utolsó automatikus: <b>${aw}</b>${ast ? ' &middot; ' + ast : ''}</span>`);
            }

            lastHtml = parts.join('<span class="text-secondary mx-1 sched-last-sep">|</span>');
        }
        $('#schedulerLastText').html(lastHtml);

        // 4) Mobil: egysoros státuszsáv + a részletek modál tartalma
        const compact = schedulerCompactState(sched);
        $('#schedulerCompactIcon').html(compact.icon);
        $('#schedulerCompactText')
            .removeClass('text-secondary text-primary text-danger text-success '
                       + 'text-warning-emphasis fw-semibold')
            .addClass(compact.cls)
            .text(compact.text);
        $('#schedModalState').html(stateHtml + ' &middot; ' + compact.text);
        const help = schedulerHelpText(sched);
        $('#schedulerCompact').attr('title', help || 'Szinkronizálás részletei');
        $('#schedModalHelp').toggleClass('d-none', !help).text(help);
        $('#schedModalWindow').html(
            schedulerWindowHtml(sched)
            + ` <span class="text-secondary">(${sched.interval_minutes} percenként)</span>`);
        $('#schedModalNext').html(nextModalHtml);
        $('#schedModalLast').html(lastHtml);
    }

    function checkSyncStatus() {
        $.getJSON('/api/sync/status', function(res) {
            let logTerminal = $('#logTerminal');
            let logContainer = $('#syncLogContainer');
            let btn = $('#btnSync');
            let spinner = $('#syncSpinner');
            let title = $('#syncStatusTitle');
            let btnStop = $('#btnStopSync');

            refreshSchedulerInfo(res.scheduler);

            if (res.running) {
                btn.prop('disabled', true).html('<i class="fa-solid fa-spinner fa-spin me-2"></i>Szinkronizálás...');
                logContainer.removeClass('d-none');
                spinner.removeClass('d-none');
                title.text(res.trigger === 'scheduled'
                    ? 'Ütemezett szinkronizálás folyamatban a háttérben...'
                    : 'Szinkronizálás folyamatban a háttérben...');
                btnStop.removeClass('d-none');

                if (res.logs.length > 0) {
                    logTerminal.empty();
                    res.logs.forEach(function(line) {
                        logTerminal.append(`<div>> ${line}</div>`);
                    });
                    logTerminal.scrollTop(logTerminal[0].scrollHeight);
                }

                if (!syncInterval) {
                    syncInterval = setInterval(checkSyncStatus, 1500);
                }
            } else {
                btn.prop('disabled', false).html('<i class="fa-solid fa-rotate me-1"></i>Frissítés');
                spinner.addClass('d-none');
                btnStop.addClass('d-none');

                if (res.status === 'done') {
                    title.text('Szinkronizáció kész!');
                } else if (res.status === 'done_with_errors') {
                    const hibas = (res.failed_students || []).join(', ');
                    title.text('Szinkronizáció kész — részleges hiba' + (hibas ? ` (${hibas})` : ''));
                } else if (res.status === 'stopped') {
                    title.text('Szinkronizáció leállítva!');
                } else if (res.status === 'error') {
                    title.text('Szinkronizálási hiba!');
                }

                if (syncInterval) {
                    clearInterval(syncInterval);
                    syncInterval = null;
                    // A tanév-lista is frissülhet (pl. tanévzáró után új tanév),
                    // a felhasználó választását megtartva (Kaneo #51/#52).
                    betoltTanevek(true);
                    if (orarendCalendar) orarendCalendar.refetchEvents();
                    if (calendar) calendar.refetchEvents();
                    if ($('#logs-tab').hasClass('active')) fetchSyncLogFile();
                }
            }
        });
    }

    // A tanév-választó betöltése után indulnak a tanév-függő nézetek
    // (az aktuális tanév az alapértelmezés, Kaneo #40).
    betoltTanevek();
    checkSyncStatus();
    refreshSchedulerInfo();

    // Mobilon a szűrőpanel alapból csukva legyen, hogy a fülek rögtön látszódjanak
    if (window.innerWidth < 768) {
        let cf = document.getElementById('collapseFilter');
        if (cf) bootstrap.Collapse.getOrCreateInstance(cf, { toggle: false }).hide();
    }
    // Az ütemező feliratot a futás közbeni 1,5 mp-es pollozástól függetlenül
    // percenként frissítjük (a /api/scheduler/status könnyű végpont).
    setInterval(function() { refreshSchedulerInfo(); }, 60000);

    // Kinyitó / összecsukó gomb ikonjának cseréje (+ / -)
    $('#collapseRewardDetails').on('show.bs.collapse', function () {
        $('#iconToggleRewardDetails').removeClass('fa-plus').addClass('fa-minus');
    }).on('hide.bs.collapse', function () {
        $('#iconToggleRewardDetails').removeClass('fa-minus').addClass('fa-plus');
    });

    $('button[data-bs-toggle="tab"]').on('shown.bs.tab', function (e) {
        if (e.target.id === 'attekintes-tab') {
            // Visszaérkezéskor azonnal számoljunk a már letöltött dashboard-adatból,
            // majd frissítsük is — F5 nélkül is teljes képet adjon (Kaneo #76).
            updateDashboard();
            renderDashboardFeeds();
            loadDashboardData();
            loadDashboardSummary();
        }

        if (e.target.id === 'ma-tab') {
            loadMaNezet();
        }

        if (e.target.id === 'logs-tab') {
            loadSyncRuns();
        }

        // A rejtett fülben inicializált táblázatoknál a Responsive nem tud
        // összecsukni — itt újraszámoljuk (mobil nézet).
        setTimeout(function() {
            try {
                if (typeof dataTable !== 'undefined' && dataTable.responsive) dataTable.responsive.recalc();
                if (typeof uzenetekTable !== 'undefined' && uzenetekTable.responsive) uzenetekTable.responsive.recalc();
                if (typeof hianyzasokTable !== 'undefined' && hianyzasokTable.responsive) hianyzasokTable.responsive.recalc();
                if (typeof igazolasokTable !== 'undefined' && igazolasokTable.responsive) igazolasokTable.responsive.recalc();
            } catch (err) { /* csendben */ }
        }, 60);

        if (e.target.id === 'hianyzasok-tab') {
            loadHianyzasok();
        } else if (e.target.id === 'orarend-tab') {
            if (!orarendCalendar) {
                initOrarendCalendar();
            } else {
                orarendCalendar.refetchEvents();
                orarendCalendar.updateSize();
            }
        } else if (e.target.id === 'rewards-tab') {
            loadRewardsData();
            const statDiak = $('#rewardFilterDiak').val();
            if (statDiak) $('#riportDiak').val(statDiak);
        } else if (e.target.id === 'naptar-tab') {
            if (!calendar) {
                initCalendar();
            } else {
                calendar.refetchEvents();
                calendar.updateSize();
            }
        } else if (e.target.id === 'logs-tab') {
            fetchSyncLogFile();
        }
    });

    $('#btnRefreshLogs').click(function() {
        fetchSyncLogFile();
        loadSyncRuns();
    });

    $('#btnClearLogs').click(function() {
        if (confirm('Biztosan ki akarod üríteni a sync.log fájlt?')) {
            $.post('/api/logs/clear', function(res) {
                if (res.status === 'ok') {
                    fetchSyncLogFile();
                }
            });
        }
    });

    $('#filterDiak').change(function() {
        let selectedDiak = $(this).val();
        if (selectedDiak) {
            $('#rewardFilterDiak').val(selectedDiak);
        }
        $('#naptarFilterDiak').val(selectedDiak);
        $('#orarendFilterDiak').val(selectedDiak);
        $('#hianyzasFilterDiak').val(selectedDiak);
        loadData();
        loadHianyzasok();
        if (orarendCalendar) orarendCalendar.refetchEvents();
        if (calendar) calendar.refetchEvents();
    });

    $('#filterTipus, #filterTantargy').change(function() {
        loadData();
    });

    $('#filterBejKezdoDatum, #filterBejZaroDatum, #filterHatKezdoDatum, #filterHatZaroDatum, #filterStatus').change(function() {
        applyFilters();
    });

    $('#btnQuickToday').click(function() {
        let now = new Date();
        let todayStr = fmtDate(now);
        let r = clampTanevRange(todayStr, todayStr);

        $('#filterBejKezdoDatum').val(r.kezdo);
        $('#filterBejZaroDatum').val(r.zaro);
        $('#filterHatKezdoDatum, #filterHatZaroDatum').val('');
        $('#filterStatus').val('');

        applyFilters();
    });

    $('#btnQuickThisMonthEvents').click(function() {
        let now = new Date();
        let y = now.getFullYear();
        let m = now.getMonth();
        let firstDay = new Date(y, m, 1);
        let lastDay = new Date(y, m + 1, 0);
        let r = clampTanevRange(fmtDate(firstDay), fmtDate(lastDay));

        $('#filterBejKezdoDatum').val(r.kezdo);
        $('#filterBejZaroDatum').val(r.zaro);
        $('#filterHatKezdoDatum, #filterHatZaroDatum').val('');
        $('#filterStatus').val('');

        applyFilters();
    });

    $('#btnQuickLastMonthEvents').click(function() {
        let now = new Date();
        let y = now.getFullYear();
        let m = now.getMonth() - 1;
        if (m < 0) { m = 11; y--; }
        let firstDay = new Date(y, m, 1);
        let lastDay = new Date(y, m + 1, 0);
        let r = clampTanevRange(fmtDate(firstDay), fmtDate(lastDay));

        $('#filterBejKezdoDatum').val(r.kezdo);
        $('#filterBejZaroDatum').val(r.zaro);
        $('#filterHatKezdoDatum, #filterHatZaroDatum').val('');
        $('#filterStatus').val('');

        applyFilters();
    });

    $('#btnQuickActive').click(function() {
        $('#filterBejKezdoDatum').val('');
        $('#filterBejZaroDatum').val('');
        $('#filterHatKezdoDatum, #filterHatZaroDatum').val('');
        $('#filterStatus').val('aktiv');
        applyFilters();
    });

    // ── Tanulmányi Excel exportok (Kaneo #83) ──────────────────────────────
    function exportIdoszakParams(kezdo, zaro) {
        let out = '';
        if (kezdo) out += `&kezdo_datum=${encodeURIComponent(kezdo)}`;
        if (zaro) out += `&zaro_datum=${encodeURIComponent(zaro)}`;
        return out;
    }

    $('#btnEsemenyExportXlsx').on('click', function() {
        // A jelenlegi szűrt eredmény exportja (ugyanazok a szűrők, mint a listán).
        let url = `/api/esemenyek/export.xlsx?diak=${encodeURIComponent($('#filterDiak').val() || '')}`;
        const tipus = $('#filterTipus').val() || '';
        const tantargy = $('#filterTantargy').val() || '';
        const status = $('#filterStatus').val() || '';
        if (tipus) url += `&tipus=${encodeURIComponent(tipus)}`;
        if (tantargy) url += `&tantargy=${encodeURIComponent(tantargy)}`;
        if (status) url += `&status=${encodeURIComponent(status)}`;
        url += exportIdoszakParams($('#filterBejKezdoDatum').val(), $('#filterBejZaroDatum').val());
        const hk = $('#filterHatKezdoDatum').val();
        const hz = $('#filterHatZaroDatum').val();
        if (hk) url += `&hatarido_kezdo=${encodeURIComponent(hk)}`;
        if (hz) url += `&hatarido_zaro=${encodeURIComponent(hz)}`;
        url += tanevQueryParam();
        window.location.href = url;
    });

    $('#btnHianyzasExportXlsx').on('click', function() {
        // A hiányzások/igazolások mindig a teljes tanévre mennek (Excelben szűrhető).
        let url = `/api/hianyzasok/export.xlsx?diak=${encodeURIComponent($('#hianyzasFilterDiak').val() || '')}`;
        url += tanevQueryParam();
        window.location.href = url;
    });

    // ── Aktuális bizonyítvány PDF (Kaneo #82) — mentés nélkül, azonnali generálás ──
    $('#btnRiportGeneral').on('click', function() {
        const diak = $('#riportDiak').val() || '';
        if (!diak) {
            alert('Válassz gyermeket.');
            return;
        }
        let url = `/api/riportkartya/export_pdf?diak=${encodeURIComponent(diak)}` +
                  `&periodus=${encodeURIComponent($('#riportPeriodus').val() || 'ev')}`;
        const tanev = kivalasztottTanev();
        if (tanev) url += `&tanev=${encodeURIComponent(tanev)}`;
        window.open(url, '_blank', 'noopener');
    });

    $('#rewardFilterDiak, #rewardKezdoDatum, #rewardZaroDatum').change(function() {
        if (this.id === 'rewardFilterDiak') {
            const d = $(this).val();
            if (d) $('#riportDiak').val(d);
        }
        loadRewardsData();
    });

    $('#btnResetFilters').click(function() {
        $('#filterDiak').val('');
        $('#filterTipus').val('');
        $('#filterTantargy').val('');
        $('#filterStatus').val('');

        $('#filterBejKezdoDatum').val('');
        $('#filterBejZaroDatum').val('');
        $('#filterHatKezdoDatum').val('');
        $('#filterHatZaroDatum').val('');
        $('.chip-diak').removeClass('active').filter(function () {
            return ($(this).data('diak') || '') === '';
        }).addClass('active');

        $('#naptarFilterDiak').val('');
        $('#orarendFilterDiak').val('');

        loadData();
        if (orarendCalendar) orarendCalendar.refetchEvents();
        if (calendar) calendar.refetchEvents();
    });

    // ── Dashboard: csempék, gyermek-chipek, visszalépés ────────────────────
    $('#filterDiakChips, #dashboardDiakChips, #maDiakChips').on('click', '.chip-diak', function() {
        setDiakFilter($(this).data('diak') || '');
    });

    function lastNDaysRange(days) {
        let today = new Date();
        let from = new Date(today.getFullYear(), today.getMonth(), today.getDate() - days);
        return { kezdo: fmtDate(from), zaro: fmtDate(today) };
    }

    function nextNDaysRange(days) {
        let today = new Date();
        let to = new Date(today.getFullYear(), today.getMonth(), today.getDate() + days);
        return { kezdo: fmtDate(today), zaro: fmtDate(to) };
    }

    $('#dashboardDiakCards').on('click', '.diak-atlag-kartya', function() {
        openStatisztikaForDiak($(this).data('diak'));
    }).on('keydown', '.diak-atlag-kartya', function(e) {
        if (e.key !== 'Enter' && e.key !== ' ') return;
        e.preventDefault();
        openStatisztikaForDiak($(this).data('diak'));
    });

    $('#tileHazi').on('click keydown', function(e) {
        if (e.type === 'keydown' && e.key !== 'Enter' && e.key !== ' ') return;
        let r = nextNDaysRange(10);
        let diak = $('.chip-diak.active').first().data('diak') || '';
        goToEvents({ diak: diak, tipus: 'Házi feladat', status: '', kezdo: '', zaro: '',
                     hatKezdo: r.kezdo, hatZaro: r.zaro });
    });

    $('#tileSzam').on('click keydown', function(e) {
        if (e.type === 'keydown' && e.key !== 'Enter' && e.key !== ' ') return;
        let r = nextNDaysRange(10);
        let diak = $('.chip-diak.active').first().data('diak') || '';
        goToEvents({ diak: diak, tipus: 'Bejelentett számonkérés', status: '', kezdo: '', zaro: '',
                     hatKezdo: r.kezdo, hatZaro: r.zaro });
    });

    $('#tileUjJegyek').on('click keydown', function(e) {
        if (e.type === 'keydown' && e.key !== 'Enter' && e.key !== ' ') return;
        let r = lastNDaysRange(10);
        let diak = $('.chip-diak.active').first().data('diak') || '';
        goToEvents({ diak: diak, tipus: 'Értékelés', status: '', kezdo: r.kezdo, zaro: r.zaro,
                     hatKezdo: '', hatZaro: '' });
    });

    $('#tileUjUzenetek').on('click keydown', function(e) {
        if (e.type === 'keydown' && e.key !== 'Enter' && e.key !== ' ') return;
        showMainTab('uzenetek-tab');
    });

    $('#tileIgazolatlan').on('click keydown', function(e) {
        if (e.type === 'keydown' && e.key !== 'Enter' && e.key !== ' ') return;
        showMainTab('hianyzasok-tab');
    });

    $('#tileZsebpenz').on('click keydown', function(e) {
        if (e.type === 'keydown' && e.key !== 'Enter' && e.key !== ' ') return;
        showMainTab('rewards-tab');
    });

    $('.app-brand').on('click', function(e) {
        // A logó valódi link (href="/"), de ne töltse újra az oldalt:
        // váltson az Áttekintés fülre. Új lapon nyitást engedjük.
        if (e.ctrlKey || e.metaKey || e.shiftKey || e.altKey || e.button !== 0) return;
        e.preventDefault();
        showMainTab('attekintes-tab');
        window.scrollTo({top: 0, behavior: 'smooth'});
    });

    $('.btn-back-dashboard, #btnDashboardToList').on('click', function() {
        showMainTab($(this).hasClass('btn-back-dashboard') ? 'attekintes-tab' : 'esemenyek-tab');
    });

    function updateModalOlvasottButton(olvasott) {
        let $btn = $('#btnModalToggleOlvasott');
        if (olvasott) {
            $btn.html('<i class="fa-solid fa-envelope me-1"></i>Olvasatlannak jelölés');
        } else {
            $btn.html('<i class="fa-solid fa-envelope-open me-1"></i>Olvasottnak jelölés');
        }
    }

    function setUzenetOlvasott(msgId, olvasott, doneCb) {
        $.ajax({
            url: `/api/uzenetek/${msgId}/olvasott`,
            type: 'POST',
            contentType: 'application/json',
            data: JSON.stringify({ olvasott: !!olvasott }),
            success: function() {
                applyUzenetOlvasottLocal([msgId], !!olvasott);
                if (typeof doneCb === 'function') doneCb();
            }
        });
    }

    // A helyi (memória + DataTable) állapot frissítése mentés után.
    function applyUzenetOlvasottLocal(ids, olvasott) {
        let idSet = new Set((ids || []).map(Number));
        let mind = idSet.size === 0;
        (rawUzenetek || []).forEach(function(m) {
            if (mind || idSet.has(m.id)) m.olvasott = !!olvasott;
        });
        uzenetekTable.rows().every(function() {
            let d = this.data();
            if (d && (mind || idSet.has(d.id))) {
                d.olvasott = !!olvasott;
                this.data(d);
                $(this.node()).toggleClass('uzenet-olvasatlan', !olvasott);
            }
        });
        uzenetekTable.draw(false);
        updateUzenetOlvasatlanBadge();
        if (mind || idSet.has(uzenetAktualisId)) {
            updateModalOlvasottButton(!!olvasott);
        }
    }

    // Tömeges állapotváltás: kijelölt azonosítók, vagy (ids nélkül) a diák-szűrés
    // szerinti összes üzenet (Kaneo #11).
    function setUzenetOlvasottBulk(ids, olvasott, doneCb) {
        let payload = { olvasott: !!olvasott };
        if (Array.isArray(ids) && ids.length) {
            payload.ids = ids;
        } else {
            payload.diak = $('#filterDiak').val() || '';
        }
        $.ajax({
            url: '/api/uzenetek/olvasott',
            type: 'POST',
            contentType: 'application/json',
            data: JSON.stringify(payload),
            success: function() {
                applyUzenetOlvasottLocal(Array.isArray(ids) && ids.length ? ids : [], !!olvasott);
                uzenetKijelolt.clear();
                updateUzenetKijeloles();
                if (typeof doneCb === 'function') doneCb();
            },
            error: function(xhr) {
                alert((xhr.responseJSON && xhr.responseJSON.message) || 'Az állapot mentése nem sikerült.');
            }
        });
    }

    $('#uzenetekTable').on('change', '.uzenet-select', function(e) {
        e.stopPropagation();
        let id = Number($(this).data('id'));
        if (!id) return;
        if ($(this).is(':checked')) {
            uzenetKijelolt.add(id);
        } else {
            uzenetKijelolt.delete(id);
        }
        updateUzenetKijeloles();
    });

    $('#uzenetSelectAll').on('click', function(e) {
        e.stopPropagation();
    }).on('change', function() {
        let checked = $(this).is(':checked');
        uzenetKijelolt.clear();
        if (checked) {
            uzenetekTable.rows({ search: 'applied' }).every(function() {
                let d = this.data();
                if (d && d.id) uzenetKijelolt.add(d.id);
            });
        }
        uzenetekTable.draw(false);
        updateUzenetKijeloles();
    });

    $('#btnUzenetKijeloltOlvasott').on('click', function() {
        let ids = Array.from(uzenetKijelolt);
        if (!ids.length) return;
        setUzenetOlvasottBulk(ids, true);
    });

    $('#btnUzenetKijeloltOlvasatlan').on('click', function() {
        let ids = Array.from(uzenetKijelolt);
        if (!ids.length) return;
        setUzenetOlvasottBulk(ids, false);
    });

    $('#btnUzenetKijelolesTorles').on('click', function() {
        uzenetKijelolt.clear();
        uzenetekTable.draw(false);
        updateUzenetKijeloles();
    });

    $('#btnUzenetMindOlvasott').on('click', function() {
        setUzenetOlvasottBulk([], true);
    });

    $('#btnUzenetMindOlvasatlan').on('click', function() {
        if (!confirm('A lista összes üzenete olvasatlanná válik. Folytatod?')) return;
        setUzenetOlvasottBulk([], false);
    });

    $('#uzenetOlvasottFilter').on('click', 'button[data-filter]', function() {
        $('#uzenetOlvasottFilter button').removeClass('active');
        $(this).addClass('active');
        uzenetOlvasottMode = $(this).data('filter') || 'all';
        uzenetekTable.draw();
    });

    $('#uzenetekTable').on('click', '.btn-toggle-msg-read', function(e) {
        e.stopPropagation();
        let id = Number($(this).data('id'));
        let target = (rawUzenetek || []).find(function(m) { return m.id === id; });
        if (!target) return;
        setUzenetOlvasott(id, !target.olvasott);
    });

    $('#btnModalToggleOlvasott').on('click', function() {
        if (!uzenetAktualisId) return;
        let target = (rawUzenetek || []).find(function(m) { return m.id === uzenetAktualisId; });
        if (!target) return;
        setUzenetOlvasott(uzenetAktualisId, !target.olvasott);
    });

    function openUzenetModal(msg) {
        $('#uzenetModalTitle').html(`<i class="fa-solid fa-envelope-open me-2"></i>${msg.targy}`);
        $('#modalFelado').text(msg.felado);
        $('#modalIdopont').text(msg.idopont);
        $('#modalDiak').text(msg.diak_nev);
        $('#modalSzoveg').text(msg.szoveg || '(Üres üzenet)');

        if (msg.csatolmany_utvonal) {
            $('#modalCsatolmanyContainer').removeClass('d-none');
            $('#modalCsatolmanyNev').text(` ${msg.csatolmany_nev}`);
            // A DB-ben történetileg több formátum szerepel: "static/csatolmanyok/...",
            // "/app/data/csatolmanyok/..." és tiszta "diak/fajl.pdf" — mindegyikből
            // a tiszta relatív nevet állítjuk elő, és a route prefixet mi tesszük elé
            // (a `//app/...` protokoll-relatív URL halott link lenne).
            let csRel = String(msg.csatolmany_utvonal)
                .replace(/\\/g, '/')
                .replace(/^\/+/, '')
                .replace(/^.*csatolmanyok\//, '');
            $('#modalCsatolmanyLink').attr('href', '/static/csatolmanyok/' + encodeURI(csRel));
        } else {
            $('#modalCsatolmanyContainer').addClass('d-none');
        }

        // Saját megjegyzések (Kaneo #46)
        uzenetKommentCel = { kulcs: msg.komment_kulcs || '', diak: msg.diak_nev || '' };
        $('#uzenetKommentUj').val('');
        betoltUzenetKommentek();

        // Naptárbejegyzés (Kaneo #47) + olvasottság (Kaneo #11)
        uzenetAktualisId = msg.id;
        updateModalOlvasottButton(true);
        if (!msg.olvasott) {
            setUzenetOlvasott(msg.id, true);
        }

        let myModal = new bootstrap.Modal(document.getElementById('uzenetModal'));
        myModal.show();
    }

    $('#uzenetekTable').on('click', '.btn-read-msg', function() {
        let idx = $(this).data('index');
        let msg = uzenetekTable.row(idx).data();
        if (!msg) {
            let id = Number($(this).data('id'));
            msg = (rawUzenetek || []).find(function(m) { return m.id === id; });
        }
        if (!msg) return;
        openUzenetModal(msg);
    });

    // Naptárbejegyzés: Google Naptár (előre kitöltött esemény) — Kaneo #47
    $(document).on('click', '.btn-naptar-google, #btnUzenetNaptarGoogle', function(e) {
        e.preventDefault();
        let kind = $(this).data('kind') || 'uzenet';
        let id = $(this).data('id') || uzenetAktualisId;
        if (!id) return;
        $.getJSON(`/api/naptar/${kind}/${id}`, function(res) {
            if (res && res.google_url) {
                window.open(res.google_url, '_blank', 'noopener');
            }
        }).fail(function(xhr) {
            alert((xhr.responseJSON && xhr.responseJSON.message) || 'A naptárbejegyzés nem készíthető el.');
        });
    });

    // ── Üzenet AI-elemzése (Kaneo #61) ─────────────────────────────────────
    // A felületi gombot a felhasználó kérésére kivettük (2026-11-04): a háttér
    // (/api/uzenet/<id>/ai, /api/naptar/ai/ics) megmaradt, API-ból hívható.

    $('#btnUzenetKommentMent').click(function() {
        let szoveg = $('#uzenetKommentUj').val().trim();
        if (!szoveg || !uzenetKommentCel.kulcs) return;
        $.ajax({
            url: '/api/kommentek',
            type: 'POST',
            contentType: 'application/json',
            data: JSON.stringify({
                cel_tipus: 'uzenet',
                cel_kulcs: uzenetKommentCel.kulcs,
                diak_nev: uzenetKommentCel.diak,
                szoveg: szoveg
            }),
            success: function() {
                $('#uzenetKommentUj').val('');
                betoltUzenetKommentek();
            }
        });
    });

    $('#collapseTerminal').on('show.bs.collapse', function () {
        $('#collapseIcon').removeClass('fa-chevron-down').addClass('fa-chevron-up');
    }).on('hide.bs.collapse', function () {
        $('#collapseIcon').removeClass('fa-chevron-up').addClass('fa-chevron-down');
    });

    $('#btnCloseLog').click(function(e) {
        e.stopPropagation();
        $('#syncLogContainer').addClass('d-none');
    });

    function startSync() {
        $.ajax({
            url: '/api/sync/start',
            type: 'POST',
            contentType: 'application/json',
            data: JSON.stringify({}),
            success: function(res) {
                if (res.status === 'started' || res.status === 'already_running') {
                    checkSyncStatus();
                } else if (res.message) {
                    alert(res.message);
                }
            },
            error: function(xhr) {
                let msg = (xhr.responseJSON && xhr.responseJSON.message)
                    || 'A szinkronizáció nem indult el.';
                alert(msg);
            }
        });
    }

    $('#btnSync').click(function() {
        startSync();
    });

    $('#btnStopSync').click(function(e) {
        e.stopPropagation();
        if (confirm('Biztosan le akarod állítani a KRÉTA szinkronizálást?')) {
            $.post('/api/sync/stop', function(res) {
                checkSyncStatus();
            });
        }
    });

    // ── Globális kereső (Kaneo #85) ────────────────────────────────────────
    let keresesTimer = null;
    let keresesTalalatok = [];
    let keresesAktualis = -1;
    let keresesKiemelId = null;
    const KERESES_ELOZMENY_KULCS = 'kreta_kereses_elozmeny';

    function keresesElozmenyLista() {
        try {
            const lista = JSON.parse(localStorage.getItem(KERESES_ELOZMENY_KULCS) || '[]');
            return Array.isArray(lista) ? lista.filter(function(x) { return typeof x === 'string'; }) : [];
        } catch (e) {
            return [];
        }
    }

    function keresesElozmenyMent(q) {
        q = String(q || '').trim();
        if (q.length < 2) return;
        const lista = [q].concat(keresesElozmenyLista().filter(function(x) { return x !== q; })).slice(0, 5);
        try { localStorage.setItem(KERESES_ELOZMENY_KULCS, JSON.stringify(lista)); } catch (e) {}
        renderKeresesElozmeny();
    }

    function renderKeresesElozmeny() {
        const $box = $('#keresesElozmeny');
        const lista = keresesElozmenyLista();
        if (!lista.length) {
            $box.addClass('d-none').empty();
            return;
        }
        $box.removeClass('d-none').html(
            '<span class="text-muted me-1">Legutóbbi keresések:</span>' +
            lista.map(function(q) {
                return `<button type="button" class="btn btn-sm btn-outline-secondary py-0 px-2 me-1 mb-1 kereses-elozmeny"
                        data-q="${escapeHtml(q)}">${escapeHtml(q)}</button>`;
            }).join(''));
    }

    function keresesModalNyitas() {
        const el = document.getElementById('keresesModal');
        if (!el) return;
        const input = document.getElementById('keresesInput');
        const fokusz = function() {
            if (!input) return;
            input.focus({preventScroll: true});
            try { input.select(); } catch (e) { /* nem kritikus */ }
        };
        // A Bootstrap a megjelenítés végén a modálra teszi a fókuszt, ezért a
        // „shown” esemény után kell a keresőmezőre állítani (Kaneo #117).
        el.addEventListener('shown.bs.modal', fokusz, {once: true});
        bootstrap.Modal.getOrCreateInstance(el).show();
        setTimeout(fokusz, 350);   // tartalék, ha a shown nem fut le
        renderKeresesElozmeny();
    }

    function keresesBadge(t) {
        // Ugyanazok a feliratok és színek, mint az Események fülön (Kaneo #85).
        if (t.tipus === 'uzenet') return { cls: 'bg-info text-dark', text: 'Üzenet' };
        if (t.tipus === 'hianyzas') return { cls: 'bg-danger', text: 'Hiányzás' };
        if (t.esemeny_tipus === 'Értékelés') return { cls: 'badge-ertekeles', text: 'Értékelés' };
        if (t.esemeny_tipus === 'Feljegyzés') return { cls: 'badge-feljegyzes', text: 'Feljegyzés' };
        if (t.esemeny_tipus === 'Házi feladat') return { cls: 'badge-hazi', text: 'Házi feladat' };
        if (t.esemeny_tipus === 'Bejelentett számonkérés') {
            return { cls: 'badge-szamonkeres', text: 'Bejelentett számonkérés' };
        }
        return { cls: 'bg-secondary', text: t.esemeny_tipus || 'Esemény' };
    }

    function renderKereses(res) {
        keresesTalalatok = res.talalatok || [];
        keresesAktualis = -1;
        let $box = $('#keresesEredmeny').empty();
        if (!keresesTalalatok.length) {
            $box.append('<div class="text-muted small p-2">Nincs találat.</div>');
            return;
        }
        keresesTalalatok.forEach(function(t, idx) {
            const b = keresesBadge(t);
            const datum = t.datum ? fmtIsoToHu(t.datum) : '';
            let html = `<button type="button" class="list-group-item list-group-item-action kereses-talalat p-2" data-idx="${idx}">
                <div class="d-flex justify-content-between align-items-start gap-2">
                    <div class="text-truncate">
                        <span class="badge ${b.cls} me-1">${escapeHtml(b.text)}</span>
                        <span class="fw-semibold">${escapeHtml(t.cim || '')}</span>
                    </div>
                    <small class="text-muted text-nowrap">${escapeHtml(datum)}</small>
                </div>`;
            if (t.reszlet) {
                html += `<div class="small text-muted text-truncate mt-1">${escapeHtml(t.reszlet)}</div>`;
            }
            html += `<div class="small text-secondary mt-1">${escapeHtml(t.diak || '')}</div></button>`;
            $box.append(html);
        });
    }

    function keresesFuttat(q) {
        if (!q || q.length < 2) return;
        $.getJSON(`/api/kereses?q=${encodeURIComponent(q)}&limit=20`)
            .done(renderKereses)
            .fail(function() {
                $('#keresesEredmeny').html('<div class="text-danger small p-2">A keresés nem sikerült.</div>');
            });
    }

    function esemenyReszletekSzoveg(e) {
        const sorok = [];
        function sor(cimke, ertek) {
            if (ertek === undefined || ertek === null) return;
            const t = String(ertek).trim();
            if (!t || t === '-') return;
            sorok.push(cimke + ': ' + t);
        }
        sor('Diák', e.diak_nev);
        sor('Típus', e.esemeny_tipus);
        sor('Tantárgy', e.tantargy);
        let ertek = e.ertek;
        if (e.mod && e.mod !== '-') ertek = (ertek || '') + ' (' + e.mod + ')';
        if (Number(e.suly_szazalek) > 0) ertek = (ertek || '') + ' — súly: ' + e.suly_szazalek + '%';
        sor('Érték', ertek);
        sor('Bejegyzés dátuma', e.bej_datum);
        sor('Bekerült a SuliHubba', e.letrehozva);
        sor('Határidő', e.hatarido);
        sor('Értékelő / tanár', e.ertekelo);
        sor('Téma', e.tema);
        sor('Cím', e.cim);
        if (e.esemeny_tipus === 'Házi feladat') {
            sor('Állapot', Number(e.kesz) === 1 ? 'Elkészítve' : 'Aktív');
        }
        sor('Leírás', e.tartalom);
        return sorok.join('\n');
    }

    function hianyzasReszletekSzoveg(h) {
        const sorok = [];
        function sor(cimke, ertek) {
            if (ertek === undefined || ertek === null) return;
            const t = String(ertek).trim();
            if (!t || t === '-') return;
            sorok.push(cimke + ': ' + t);
        }
        sor('Diák', h.diak_nev);
        sor('Dátum', fmtIsoToHu(h.mulasztas_datum));
        sor('Óra', h.ora_sorszam ? h.ora_sorszam + '.' : '');
        sor('Tantárgy', h.tantargy);
        sor('Téma', h.tema);
        sor('Tanár', h.tanar);
        sor('Típus', h.mulasztas_tipus);
        sor('Igazolt', Number(h.igazolt) === 1 ? 'Igen' : 'Nem');
        sor('Igazolás típusa', h.igazolas_tipus);
        sor('Tanórai cél', h.tanorai_celu);
        sor('Rögzítés dátuma', h.rogzites_datum);
        if (h.perc) sor('Késés', h.perc + ' perc');
        return sorok.join('\n');
    }

    const RESZLETEK_LEIRAS_CIMKE = /^(leírás|leírás \/ részletek|megjegyzés|tartalom)$/i;

    function reszletekParse(szoveg) {
        const rows = [];
        const sections = [];
        let aktualis = null;
        String(szoveg || '').split(/\r?\n/).forEach(function(raw) {
            const line = raw.trim();
            if (!line) return;
            // Egy megkezdett szakaszon (Leírás / Megjegyzés) belül minden sor
            // ehhez a szakaszhoz tartozik — akkor is, ha kettőspont van benne
            // (pl. „… a tanult módon: módja, ideje …”), különben a szöveg
            // címke–érték sorként széttörné a megjelenítést (Kaneo #126).
            if (aktualis) {
                aktualis.sorok.push(line);
                return;
            }
            const m = line.match(/^([^:]{1,40}):\s*(.*)$/);
            if (m) {
                const cimke = m[1].trim();
                const ertek = m[2].trim();
                if (ertek && !RESZLETEK_LEIRAS_CIMKE.test(cimke)) {
                    rows.push({ cimke: cimke, ertek: ertek });
                    aktualis = null;
                } else {
                    aktualis = { cim: cimke, sorok: ertek ? [ertek] : [] };
                    sections.push(aktualis);
                }
            } else {
                aktualis = { cim: '', sorok: [line] };
                sections.push(aktualis);
            }
        });
        return { rows: rows, sections: sections };
    }

    function reszletekRow(rows, nevek) {
        for (let i = 0; i < rows.length; i++) {
            const cimke = rows[i].cimke.toLowerCase();
            if (nevek.some(function(nev) { return cimke === nev; })) {
                return rows.splice(i, 1)[0];
            }
        }
        return null;
    }

    function reszletekTipusOsztaly(tipus) {
        const t = String(tipus || '').toLowerCase();
        if (t.indexOf('házi') >= 0) return 'text-bg-warning';
        if (t.indexOf('számonkérés') >= 0) return 'text-bg-danger';
        if (t.indexOf('értékelés') >= 0 || t.indexOf('jegy') >= 0) return 'text-bg-success';
        if (t.indexOf('hiányzás') >= 0 || t.indexOf('késés') >= 0) return 'text-bg-secondary';
        if (t.indexOf('feljegyzés') >= 0) return 'text-bg-info';
        return 'text-bg-primary';
    }

    function reszletekAllapotOsztaly(allapot) {
        const a = String(allapot || '').toLowerCase();
        if (a.indexOf('lejárt') >= 0 || a.indexOf('igazolatlan') >= 0) return 'text-bg-danger';
        if (a.indexOf('aktív') >= 0 || a.indexOf('elkész') >= 0 || a === 'igazolt') {
            return 'text-bg-success';
        }
        return 'text-bg-secondary';
    }

    function reszletekJegyHtml(ertek) {
        if (!ertek) return '';
        const m = String(ertek).match(/\((\d)\)/);
        const kor = m ? `<span class="jegy-kor jegy-${m[1]}">${m[1]}</span>` : '';
        return `<span class="reszletek-jegy">${kor}` +
               `<span class="reszletek-jegy-szoveg">${escapeHtml(ertek)}</span></span>`;
    }

    function reszletekRender(szoveg) {
        const parsed = reszletekParse(szoveg);
        const rows = parsed.rows;
        const tantargy = reszletekRow(rows, ['tantárgy', 'óra / esemény', 'megnevezés']);
        const tipus = reszletekRow(rows, ['típus / mód', 'típus']);
        const diak = reszletekRow(rows, ['diák']);
        const datum = reszletekRow(rows, ['határidő', 'dátum', 'időpont']);
        const allapot = reszletekRow(rows, ['állapot']);
        const igazolt = reszletekRow(rows, ['igazolt']);
        const ertek = reszletekRow(rows, ['érték']);

        let html = '';
        const heroFej = [];
        if (tantargy) {
            heroFej.push(`<span class="reszletek-tantargy">${escapeHtml(tantargy.ertek)}</span>`);
        }
        if (tipus) {
            heroFej.push(`<span class="badge reszletek-tipus ${reszletekTipusOsztaly(tipus.ertek)}">` +
                         `${escapeHtml(tipus.ertek)}</span>`);
        }
        if (allapot) {
            heroFej.push(`<span class="badge ${reszletekAllapotOsztaly(allapot.ertek)}">` +
                         `${escapeHtml(allapot.ertek)}</span>`);
        } else if (igazolt) {
            const ig = igazolt.ertek.toLowerCase() === 'igen' ? 'Igazolt' : 'Igazolatlan';
            heroFej.push(`<span class="badge ${reszletekAllapotOsztaly(ig)}">${escapeHtml(ig)}</span>`);
        }
        if (ertek) heroFej.push(reszletekJegyHtml(ertek.ertek));

        if (heroFej.length || diak || datum) {
            html += '<div class="reszletek-hero">';
            if (heroFej.length) {
                html += `<div class="reszletek-hero-fej">${heroFej.join('')}</div>`;
            }
            const also = [];
            if (diak) {
                also.push(`<span class="reszletek-hero-adat">` +
                          `<i class="fa-solid fa-user-graduate"></i>` +
                          `${escapeHtml(diak.ertek)}</span>`);
            }
            if (datum) {
                also.push(`<span class="reszletek-hero-adat">` +
                          `<i class="fa-regular fa-calendar"></i>` +
                          `${escapeHtml(datum.cimke)}: ${escapeHtml(datum.ertek)}</span>`);
            }
            if (also.length) html += `<div class="reszletek-hero-alap">${also.join('')}</div>`;
            html += '</div>';
        }

        if (rows.length) {
            html += '<div class="reszletek-meta">' + rows.map(function(row) {
                return `<div class="reszletek-meta-item">
                    <span class="reszletek-label">${escapeHtml(row.cimke)}</span>
                    <span class="reszletek-ertek">${escapeHtml(row.ertek)}</span>
                </div>`;
            }).join('') + '</div>';
        }

        parsed.sections.forEach(function(section) {
            const text = section.sorok.join('\n').trim();
            if (!text) return;
            html += `<div class="reszletek-leiras">
                <div class="reszletek-leiras-cim"><i class="fa-solid fa-align-left me-1"></i>${escapeHtml(section.cim || 'Leírás')}</div>
                <div class="reszletek-leiras-szoveg">${escapeHtml(text)}</div>
            </div>`;
        });

        return html || '<div class="text-muted">Nincs megjeleníthető részlet.</div>';
    }

    function reszletekIcon(cim) {
        const c = String(cim || '').toLowerCase();
        if (c.indexOf('házi') >= 0) return 'fa-book-open';
        if (c.indexOf('számonkérés') >= 0) return 'fa-file-pen';
        if (c.indexOf('értékelés') >= 0 || c.indexOf('jegy') >= 0) return 'fa-graduation-cap';
        if (c.indexOf('hiányzás') >= 0 || c.indexOf('késés') >= 0) return 'fa-user-clock';
        if (c.indexOf('feljegyzés') >= 0) return 'fa-note-sticky';
        if (c.indexOf('fogadóóra') >= 0) return 'fa-handshake';
        return 'fa-circle-info';
    }

    function reszletekBody(szoveg) {
        $('#detailsModalBody').html(reszletekRender(szoveg));
    }

    function reszletekModal(cim, szoveg) {
        $('#detailsModalTitle').html(`<i class="fa-solid ${reszletekIcon(cim)} me-2"></i>` +
                                     escapeHtml(cim));
        reszletekBody(szoveg);
        $('#modalActionContainer').addClass('d-none');
        bootstrap.Modal.getOrCreateInstance(document.getElementById('detailsModal')).show();
    }

    function keresesTalalatMegnyit(t) {
        const el = document.getElementById('keresesModal');
        const inst = el ? bootstrap.Modal.getInstance(el) : null;

        // A kereső ablak bezárása után nyissuk a részleteket (ne csússzon egymásra
        // a két modál, és a bezárási animáció is fusson le) — Kaneo #85.
        function bezarEs(cb) {
            if (!inst || !el || !el.classList.contains('show')) {
                cb();
                return;
            }
            el.addEventListener('hidden.bs.modal', function () { cb(); }, {once: true});
            inst.hide();
        }

        if (t.tipus === 'esemeny') {
            bezarEs(function() {
                keresesKiemelId = t.id;
                goToEvents({
                    diak: t.diak || '', tipus: t.esemeny_tipus || '',
                    tantargy: t.tantargy || '', status: '',
                    kezdo: '', zaro: '', hatKezdo: '', hatZaro: ''
                });
                $.getJSON(`/api/esemenyek?diak=${encodeURIComponent(t.diak || '')}`)
                    .done(function(list) {
                        const e = (list || []).find(function(x) {
                            return Number(x.id) === Number(t.id);
                        });
                        if (e) {
                            reszletekModal(e.esemeny_tipus || 'Esemény részletei',
                                           esemenyReszletekSzoveg(e));
                        }
                    });
            });
        } else if (t.tipus === 'uzenet') {
            bezarEs(function() {
                showMainTab('uzenetek-tab');
                let msg = (rawUzenetek || []).find(function(m) { return m.id === t.id; });
                if (msg) {
                    openUzenetModal(msg);
                } else {
                    // A keresett üzenet más diákhoz tartozhat: töltsük be arra a diákra.
                    $.getJSON(`/api/uzenetek?diak=${encodeURIComponent(t.diak || '')}`, function(list) {
                        const found = (list || []).find(function(m) { return m.id === t.id; });
                        if (found) openUzenetModal(found);
                    });
                }
            });
        } else if (t.tipus === 'hianyzas') {
            bezarEs(function() {
                $.getJSON(`/api/hianyzasok?diak=${encodeURIComponent(t.diak || '')}`)
                    .done(function(res) {
                        const h = ((res && res.rows) || []).find(function(x) {
                            return Number(x.id) === Number(t.id);
                        });
                        if (h) {
                            reszletekModal('Hiányzás részletei', hianyzasReszletekSzoveg(h));
                        } else {
                            showMainTab('hianyzasok-tab');
                            if (t.diak) $('#hianyzasFilterDiak').val(t.diak);
                            $('#hianyzasHonap').val(t.datum ? String(t.datum).slice(0, 7) : '');
                            $('#hianyzasFilterDiak').trigger('change');
                            $('#hianyzasHonap').trigger('change');
                        }
                    })
                    .fail(function() {
                        showMainTab('hianyzasok-tab');
                    });
            });
        }
    }

    // ── „Ma” önálló nézet (Kaneo #9) ────────────────────────────────────────
    // A felhasználó a dashboardon elutasította a Ma kártyát; itt külön fülként él.
    const MA_NAPOK = ['vasárnap', 'hétfő', 'kedd', 'szerda', 'csütörtök', 'péntek', 'szombat'];
    let maNezet = 'nap';
    let maAktualisDatum = null;
    // A Ma fül határidő-soraihoz tartozó teljes eseményadatok (részletek modálhoz).
    let maHataridokAdat = {};

    function maIso(d) {
        const y = d.getFullYear();
        const m = String(d.getMonth() + 1).padStart(2, '0');
        const nap = String(d.getDate()).padStart(2, '0');
        return `${y}-${m}-${nap}`;
    }

    function maDatumFelirat(datum) {
        const d = new Date(String(datum) + 'T00:00:00');
        if (isNaN(d.getTime())) return 'Ma';
        return 'Ma, ' + honapNev(String(datum).slice(0, 7)) + ' ' + d.getDate() +
               '. (' + MA_NAPOK[d.getDay()] + ')';
    }

    function maUres(text) {
        return `<div class="list-group-item text-muted">${escapeHtml(text)}</div>`;
    }

    // Határidő-sor a Ma fül mindkét listájához (ma/holnap + holnapi kártya).
    function maHataridoSor(h, minden) {
        const kesz = Number(h.kesz) === 1;
        const rovid = h.esemeny_tipus === 'Házi feladat' ? 'Házi' : 'Számonkérés';
        const nev = (minden && h.diak_nev)
            ? `<span class="text-muted ms-auto">${escapeHtml(h.diak_nev)}</span>` : '';
        maHataridokAdat[Number(h.id)] = h;
        const ido = h.mikor
            ? ` <span class="badge bg-${h.mikor === 'ma' ? 'danger' : 'secondary'}">${h.mikor}</span>`
            : '';
        return `<div class="list-group-item list-group-item-action py-1 px-2 d-flex align-items-center gap-2 ma-hatarido"
                         role="button" tabindex="0" data-id="${h.id}">
            <button class="btn btn-sm btn-link p-0 btn-ma-kesz" data-id="${h.id}"
                    data-kesz="${kesz ? 0 : 1}"
                    title="${kesz ? 'Kész jelölés visszavonása' : 'Megjelölés elkészültként'}">
                <i class="fa-${kesz ? 'solid fa-square-check text-success' : 'regular fa-square'}"></i>
            </button>${ido}
            <span class="${kesz ? 'text-decoration-line-through text-muted' : ''}">
                <b>${escapeHtml(h.tantargy)}</b> — ${escapeHtml(h.megnevezes)}
            </span>
            <span class="badge bg-light text-body border">${rovid}</span>${nev}
        </div>`;
    }

    // Óra-sor a Ma fülhöz (ma és holnap).
    function maOraSor(o, minden) {
        const nev = (minden && o.diak_nev)
            ? ` <span class="text-muted">${escapeHtml(o.diak_nev)}</span>` : '';
        const hely = [o.terem, o.tanar].filter(Boolean).join(' · ');
        return `<div class="list-group-item py-1 px-2">
            <span class="fw-bold me-2">${escapeHtml(o.kezdes)}–${escapeHtml(o.vege)}</span>
            <span>${escapeHtml(o.tantargy)}</span>${nev}
            ${hely ? '<span class="text-muted ms-2">' + escapeHtml(hely) + '</span>' : ''}
        </div>`;
    }

    function maHetBetolt() {
        const diak = $('#filterDiak').val() || '';
        const alap = maAktualisDatum || maIso(new Date());
        const d = new Date(alap + 'T00:00:00');
        const off = (d.getDay() + 6) % 7;
        const hetfo = new Date(d.getFullYear(), d.getMonth(), d.getDate() - off);
        const napok = [0, 1, 2, 3, 4, 5, 6].map(function(i) {
            return new Date(hetfo.getFullYear(), hetfo.getMonth(), hetfo.getDate() + i);
        });
        const keresek = napok.map(function(n) {
            return $.getJSON(`/api/ma?diak=${encodeURIComponent(diak)}&datum=${maIso(n)}`);
        });
        Promise.all(keresek).then(function(list) {
            // Hétvégén csak akkor jelenik meg kártya, ha van óra vagy határidő
            // (Kaneo #144: munkaszombat / pótolt tanítás).
            const kartyak = [0, 1, 2, 3, 4];
            [5, 6].forEach(function(i) {
                const res = list[i] || {};
                const hat = (res.hataridok || []).filter(function(h) { return h.mikor === 'ma'; });
                if ((res.orak || []).length || hat.length) kartyak.push(i);
            });
            const vanHetvege = kartyak.some(function(i) { return i >= 5; });
            const utolso = napok[kartyak[kartyak.length - 1]];
            const idoszak = `${honapNev(maIso(hetfo).slice(0, 7))} ${hetfo.getDate()}. – ` +
                            `${honapNev(maIso(utolso).slice(0, 7))} ${utolso.getDate()}.`;
            let html = '<div class="ma-het-wrap mx-auto">' +
                `<div class="ma-het-cim text-center text-muted small mb-2">` +
                `${escapeHtml(idoszak)} · ${vanHetvege ? 'hétfő–vasárnap' : 'hétfő–péntek'}</div><div class="ma-het-grid">`;
            kartyak.forEach(function(i) {
                const res = list[i] || {};
                const nap = napok[i];
                const iso = maIso(nap);
                const orak = res.orak || [];
                // A heti nézetben minden nap a saját határidejét mutatja (a /api/ma a
                // következő napit is visszaadja — az a holnapi kártyán jelenik meg).
                const hat = (res.hataridok || []).filter(function(h) {
                    return h.mikor === 'ma';
                });
                let szin = 'ures';
                if (orak.length && hat.length) szin = 'vegyes';
                else if (orak.length) szin = 'ora';
                else if (hat.length) szin = 'hat';
                const mai = iso === maAktualisDatum;
                const oraBlokk = orak.length ? `<div class="ma-het-blokk ma-het-blokk--ora">
                        <div class="ma-het-blokk-cim"><i class="fa-solid fa-clock me-1"></i>Órák
                            <span class="badge bg-primary-subtle text-primary-emphasis ms-1">${orak.length}</span></div>
                        ${orak.map(function(o) {
                            return `<div class="ma-het-ora">
                                <span class="ma-het-ido">${escapeHtml(o.kezdes)}</span>
                                <span class="ma-het-tantargy">${escapeHtml(o.tantargy)}</span>
                                ${o.terem ? `<span class="ma-het-terem">${escapeHtml(o.terem)}</span>` : ''}
                            </div>`;
                        }).join('')}
                    </div>` : '';
                const hatBlokk = hat.length ? `<div class="ma-het-blokk ma-het-blokk--hat">
                        <div class="ma-het-blokk-cim"><i class="fa-solid fa-bookmark me-1"></i>Határidők
                            <span class="badge bg-warning-subtle text-warning-emphasis ms-1">${hat.length}</span></div>
                        ${hat.map(function(h) {
                            const kesz = Number(h.kesz) === 1;
                            const hazi = h.esemeny_tipus === 'Házi feladat';
                            maHataridokAdat[Number(h.id)] = h;
                            return `<div class="ma-het-hat-sor ma-hatarido${kesz ? ' ma-het-kesz' : ''}"
                                        role="button" tabindex="0" data-id="${h.id}">
                                <span class="badge ${hazi ? 'bg-warning text-dark' : 'bg-danger'}">${hazi ? 'Házi' : 'Számonkérés'}</span>
                                <span class="ma-het-tantargy">${escapeHtml(h.tantargy)}</span>
                                <span class="ma-het-hat-nev">— ${escapeHtml(h.megnevezes)}</span>
                            </div>`;
                        }).join('')}
                    </div>` : '';
                const ures = (!orak.length && !hat.length)
                    ? '<div class="ma-het-ures">Nincs óra és határidő.</div>' : '';
                html += `<div class="ma-het-kartya ma-het-kartya--${szin}${mai ? ' ma-ma' : ''}">
                    <div class="ma-het-fej">
                        <span class="ma-het-napnev">${MA_NAPOK[nap.getDay()]}</span>
                        <span class="ma-het-datum">${nap.getMonth() + 1}. ${nap.getDate()}.</span>
                    </div>
                    <div class="ma-het-torzs">${oraBlokk}${hatBlokk}${ures}</div>
                </div>`;
            });
            $('#maHetNezet').html(html + '</div></div>');
        }).catch(function() {
            $('#maHetNezet').html('<div class="text-danger small">A heti nézet nem tölthető be.</div>');
        });
    }

    function maNezetValtas() {
        $('#maNapNezet').toggleClass('d-none', maNezet !== 'nap');
        $('#maHetNezet').toggleClass('d-none', maNezet !== 'het');
        $('#maNezetKapcsolo .btn').removeClass('active')
            .filter(`[data-nezet="${maNezet}"]`).addClass('active');
        if (maNezet === 'nap') {
            loadMaNezet();
        } else {
            $('#maDatumCim').html('<i class="fa-solid fa-calendar-week me-2 text-primary"></i>Heti áttekintés');
            maHetBetolt();
        }
    }

    $('#maNezetKapcsolo').on('click', '.btn', function() {
        maNezet = $(this).data('nezet') || 'nap';
        maNezetValtas();
    });

    function loadMaNezet() {
        const diak = $('#filterDiak').val() || '';
        $.getJSON(`/api/ma?diak=${encodeURIComponent(diak)}`, function(res) {
            const minden = !diak;
            maAktualisDatum = res.datum;
            if (maNezet === 'nap') {
                $('#maDatumCim').html('<i class="fa-solid fa-sun me-2 text-warning"></i>' +
                                      escapeHtml(maDatumFelirat(res.datum)));
            }

            const orak = res.orak || [];
            $('#maOraDb').text(orak.length ? `(${orak.length} óra)` : '');
            $('#maOrak').html(orak.length ? orak.map(function(o) {
                return maOraSor(o, minden);
            }).join('') : maUres('Ma nincs óra.'));

            // Holnap kártya (Kaneo #134): holnapi órák + táska + holnapi határidők
            const holnapOrak = res.holnapi_orak || [];
            const hd = res.holnapi_datum;
            if (hd) {
                const hdp = new Date(String(hd) + 'T00:00:00');
                $('#maHolnapDatum').text(isNaN(hdp.getTime()) ? '' :
                    `${honapNev(String(hd).slice(0, 7))} ${hdp.getDate()}. (${MA_NAPOK[hdp.getDay()]})`);
            } else {
                $('#maHolnapDatum').text('');
            }
            $('#maHolnapOrak').html(holnapOrak.length
                ? holnapOrak.map(function(o) { return maOraSor(o, minden); }).join('')
                : maUres('Holnap nincs óra.'));

            // Igazolandó hiányzások (Kaneo #134)
            const ig = res.igazolando || [];
            const igDb = Number(res.igazolando_db) || 0;
            $('#maIgazolandoDb').text(igDb).toggleClass('d-none', igDb === 0);
            let igHtml = ig.map(function(e) {
                const nev = (minden && e.diak_nev)
                    ? ` <span class="text-muted">· ${escapeHtml(e.diak_nev)}</span>` : '';
                const napok = (e.napok !== null && e.napok !== undefined)
                    ? `<span class="badge bg-danger-subtle text-danger-emphasis border border-danger-subtle">${e.napok} napja</span>` : '';
                const ora = e.ora ? ` · ${e.ora}. óra` : '';
                const perc = (e.perc !== null && e.perc !== undefined) ? ` · késés ${e.perc} perc` : '';
                return `<div class="list-group-item py-1 px-2 d-flex align-items-center gap-2 flex-wrap">
                    ${napok}<b>${escapeHtml(e.datum)}</b>${ora} · ${escapeHtml(e.tantargy)}${nev}
                    <span class="text-muted small ms-auto">${escapeHtml(e.tipus || '')}${perc}</span>
                </div>`;
            }).join('');
            if (igDb > ig.length) {
                igHtml += `<div class="list-group-item text-muted small">… és további ${igDb - ig.length} tétel.</div>`;
            }
            $('#maIgazolando').html(igHtml || maUres('Nincs igazolandó hiányzás.'));

            const hat = res.hataridok || [];
            $('#maHataridok').html(hat.length
                ? hat.map(function(h) { return maHataridoSor(h, minden); }).join('')
                : maUres('Ma és holnap nincs esedékes házi vagy számonkérés.'));

            const jegyek = res.uj_jegyek || [];
            $('#maJegyek').html(jegyek.length ? jegyek.map(function(j) {
                const kor = (j.szam_ertek >= 1 && j.szam_ertek <= 5)
                    ? `<span class="jegy-kor jegy-${j.szam_ertek}" title="${escapeHtml(j.ertek)}">${j.szam_ertek}</span>`
                    : `<span class="badge bg-light text-body border">${escapeHtml(j.ertek)}</span>`;
                const nev = (minden && j.diak_nev)
                    ? `<span class="text-muted">${escapeHtml(j.diak_nev)}</span>` : '';
                return `<div class="list-group-item py-1 px-2 d-flex align-items-center gap-2">
                    ${kor}<span>${escapeHtml(j.tantargy)}</span>${nev}
                    <span class="text-muted small ms-auto">${escapeHtml(j.bej_datum)}</span>
                </div>`;
            }).join('') : maUres('Az elmúlt 7 napban nincs új jegy.'));

            const db = Number(res.olvasatlan_db) || 0;
            $('#maOlvasatlanDb').text(db).toggleClass('d-none', db === 0);
            const uzenetek = res.uzenetek || [];
            $('#maUzenetek').html(uzenetek.length ? uzenetek.map(function(u) {
                const nev = (minden && u.diak_nev)
                    ? `<span class="text-muted"> — ${escapeHtml(u.diak_nev)}</span>` : '';
                return `<a href="#" class="list-group-item list-group-item-action py-1 px-2 ma-uzenet"
                           data-id="${u.id}" data-diak="${escapeHtml(u.diak_nev || '')}">
                    <b>${escapeHtml(u.felado)}</b>${nev}<br>
                    <span>${escapeHtml(u.targy)}</span>
                </a>`;
            }).join('') : maUres('Nincs olvasatlan üzenet.'));

            if (maNezet === 'het') maHetBetolt();
        });
    }

    $('#ma-pane').on('click', '.btn-ma-kesz', function(e) {
        e.preventDefault();
        e.stopPropagation();
        const $btn = $(this);
        $.ajax({
            url: '/api/esemeny/statusz',
            type: 'POST',
            contentType: 'application/json',
            data: JSON.stringify({id: Number($btn.data('id')), kesz: Number($btn.data('kesz'))}),
            success: function(res) {
                if (res.status === 'ok') {
                    loadMaNezet();
                    loadDashboardData();
                }
            }
        });
    });

    function maHataridoReszletek(h) {
        if (!h) return;
        // A /api/ma ISO-dátumot ad; a közös részletek-modál magyar formátumot vár.
        const adat = Object.assign({}, h, { hatarido: fmtIsoToHu(h.hatarido) });
        reszletekModal(h.esemeny_tipus || 'Esemény részletei', esemenyReszletekSzoveg(adat));
    }

    $('#ma-pane').on('click', '.ma-hatarido', function(e) {
        if ($(e.target).closest('.btn-ma-kesz').length) return;
        maHataridoReszletek(maHataridokAdat[Number($(this).data('id'))]);
    });

    $('#ma-pane').on('keydown', '.ma-hatarido', function(e) {
        if (e.key !== 'Enter' && e.key !== ' ') return;
        e.preventDefault();
        maHataridoReszletek(maHataridokAdat[Number($(this).data('id'))]);
    });

    $('#ma-pane').on('click', '.ma-uzenet', function(e) {
        e.preventDefault();
        const id = Number($(this).data('id'));
        const diak = $(this).data('diak') || '';
        $.getJSON(`/api/uzenetek?diak=${encodeURIComponent(diak)}`, function(list) {
            const found = (list || []).find(function(m) { return Number(m.id) === id; });
            if (found) openUzenetModal(found);
        });
    });

    // ── Tantárgyi trend + hiányzás-mintázat (Kaneo #80) ──────────────────
    function sparklineSvg(honapok) {
        const vals = Object.keys(honapok || {}).sort().map(function(h) {
            const v = honapok[h];
            return v ? v.atlag : null;
        }).filter(function(v) { return v !== null && v !== undefined; });
        if (vals.length < 2) return '<span class="text-muted">–</span>';
        const w = 64, h = 18, pad = 2;
        const pts = vals.map(function(v, i) {
            const x = pad + (i * (w - 2 * pad) / (vals.length - 1));
            const y = h - pad - ((Math.max(1, Math.min(5, v)) - 1) / 4) * (h - 2 * pad);
            return x.toFixed(1) + ',' + y.toFixed(1);
        }).join(' ');
        const javul = vals[vals.length - 1] >= vals[0];
        return `<svg width="${w}" height="${h}" viewBox="0 0 ${w} ${h}" aria-hidden="true">` +
               `<polyline fill="none" stroke="${javul ? '#198754' : '#dc3545'}" stroke-width="1.6" points="${pts}"/></svg>`;
    }

    function trendCella(t) {
        const trend = t.trend || {};
        const svg = sparklineSvg(t.honapok);
        if (trend.irany === 'nincs') return svg;
        const valtozas = trend.valtozas;
        const jel = valtozas > 0 ? '+' : '';
        const szin = trend.irany === 'javul' ? 'text-success' :
                     (trend.irany === 'romlik' ? 'text-danger' : 'text-muted');
        const figyelmeztet = trend.irany === 'romlik' && valtozas <= -0.5;
        return svg + ` <span class="${szin} small">${jel}${valtozas}</span>` +
               (figyelmeztet
                   ? ' <i class="fa-solid fa-triangle-exclamation text-danger" title="Érdemi romlás"></i>'
                   : '');
    }

    function loadTrendFigyelmeztetes() {
        const diak = $('#filterDiak').val() || '';
        $.getJSON(`/api/atlagok?diak=${encodeURIComponent(diak)}${tanevQueryParam()}`, function(res) {
            const figy = res.figyelmeztetesek || [];
            const jav = res.javulasok || [];
            const mindenDiak = !diak;   // „Mind” nézetben a gyermek nevét is kiírjuk

            function trendLista(lista) {
                return lista.map(function(f) {
                    const nev = (mindenDiak && f.diak) ? `${escapeHtml(f.diak)} – ` : '';
                    const idoszak = (f.honapok || []).map(honapNev).join(' → ');
                    const jel = Number(f.valtozas) > 0 ? '+' : '';
                    return `${nev}<b>${escapeHtml(f.tantargy)}</b> ` +
                           `<span class="text-nowrap">(${idoszak}${idoszak ? ', ' : ''}` +
                           `${jel}${f.valtozas})</span>`;
                }).join(', ');
            }

            const $box = $('#trendFigyelmeztetes');
            if (!figy.length) {
                $box.addClass('d-none').empty();
            } else {
                $box.removeClass('d-none').html(
                    '<i class="fa-solid fa-arrow-trend-down me-1"></i><b>Romló tantárgy:</b> ' +
                    trendLista(figy));
            }

            const $jav = $('#trendJavulas');
            if (!jav.length) {
                $jav.addClass('d-none').empty();
            } else {
                $jav.removeClass('d-none').html(
                    '<i class="fa-solid fa-arrow-trend-up me-1"></i><b>Javuló tantárgy:</b> ' +
                    trendLista(jav));
            }
        });
    }

    function mintazatSav(db, max) {
        const szazalek = max ? Math.round(db / max * 100) : 0;
        return `<div class="progress" style="height: 6px;">` +
               `<div class="progress-bar bg-danger" style="width:${szazalek}%"></div></div>`;
    }

    function loadHianyzasMintazat() {
        const params = new URLSearchParams();
        const diak = $('#hianyzasFilterDiak').val() || '';
        const tanev = kivalasztottTanev();
        if (diak) params.set('diak', diak);
        if (tanev) params.set('tanev', tanev);
        $.getJSON('/api/hianyzas-mintazat?' + params.toString(), function(res) {
            $('#mintazatOsszes').text((res.osszes || 0) + ' sor');
            const napok = res.hetnap || [];
            const maxNap = Math.max.apply(null, napok.map(function(n) { return n.db; }).concat([1]));
            let html = '';
            napok.forEach(function(n) {
                html += `<div class="d-flex align-items-center gap-2 mb-1">
                    <span style="width: 62px;">${escapeHtml(n.nev)}</span>
                    <div class="flex-grow-1">${mintazatSav(n.db, maxNap)}</div>
                    <span class="text-muted" style="width: 28px; text-align: right;">${n.db}</span>
                </div>`;
            });
            $('#mintazatNapok').html(html || '<span class="text-muted">Nincs adat.</span>');

            const orak = (res.ora || []).filter(function(o) { return o.ora > 0; });
            const maxOra = Math.max.apply(null, orak.map(function(o) { return o.db; }).concat([1]));
            $('#mintazatOrak').html(orak.length ? orak.slice(0, 8).map(function(o) {
                return `<div class="d-flex align-items-center gap-2 mb-1">
                    <span style="width: 18px;">${o.ora}.</span>
                    <div class="flex-grow-1">${mintazatSav(o.db, maxOra)}</div>
                    <span class="text-muted">${o.db}</span></div>`;
            }).join('') : '<span class="text-muted">Nincs adat.</span>');

            const tant = (res.tantargyak || []).slice(0, 6);
            $('#mintazatTantargyak').html(tant.length ? tant.map(function(t) {
                return `<div class="d-flex justify-content-between"><span class="text-truncate">${escapeHtml(t.tantargy)}</span>` +
                       `<span class="text-muted ms-2">${t.db}</span></div>`;
            }).join('') : '<span class="text-muted">Nincs adat.</span>');
        });
    }


    $('#btnKereses').on('click', keresesModalNyitas);
    $(document).on('keydown', function(e) {
        const key = (e.key || '').toLowerCase();
        if ((e.ctrlKey || e.metaKey) && key === 'k') {
            e.preventDefault();
            keresesModalNyitas();
        }
    });

    // ── Esti összefoglaló beállításai (KRÉ-8) ───────────────────────────────
    function digestStatus(text, ok) {
        $('#digestStatus')
            .removeClass('text-danger text-success text-muted')
            .addClass(ok === undefined ? 'text-muted' : (ok ? 'text-success' : 'text-danger'))
            .text(text || '');
    }

    function digestRovid(iso) {
        const m = String(iso || '').match(/^(\d{4})-(\d{2})-(\d{2})/);
        return m ? `${m[2]}. ${m[3]}.` : '';
    }

    function loadDigestSettings() {
        $.getJSON('/api/digest/settings', function(res) {
            const s = (res && res.settings) || {};
            $('#digestEnabled').prop('checked', s.enabled !== false);
            $('#digestTime').val(s.time || '19:30');
            $('#digestNames').prop('checked', s.include_names !== false);
            $('#digestChannel').html(res && res.ntfy_configured
                ? '<i class="fa-solid fa-circle-check text-success me-1"></i>ntfy csatorna beállítva.'
                : '<i class="fa-solid fa-triangle-exclamation text-warning me-1"></i>' +
                  'Nincs ntfy topic beállítva — az összefoglaló nem tud kimegni.');
            const last = res && res.last_auto ? String(res.last_auto) : '';
            $('#digestLastAuto').text(last
                ? 'Utolsó automatikus: ' + last.slice(0, 10).replace(/-/g, '. ') + '. ' + last.slice(11, 16)
                : 'Még nem ment ki automatikus összefoglaló.');
            digestStatus('');
        }).fail(function() {
            digestStatus('A beállítások betöltése nem sikerült.', false);
        });
    }

    $('#digestModal').on('show.bs.modal', loadDigestSettings);

    $('#btnDigestSave').on('click', function() {
        $.ajax({
            url: '/api/digest/settings', type: 'PUT', contentType: 'application/json',
            data: JSON.stringify({
                enabled: $('#digestEnabled').is(':checked'),
                time: $('#digestTime').val() || '19:30',
                include_names: $('#digestNames').is(':checked')
            })
        }).done(function() {
            digestStatus('Beállítások mentve.', true);
        }).fail(function(xhr) {
            const err = (xhr.responseJSON && xhr.responseJSON.errors) || [];
            digestStatus(err[0] || 'A mentés nem sikerült.', false);
        });
    });

    $('#btnDigestNow').on('click', function() {
        digestStatus('Küldés...');
        $.ajax({
            url: '/api/digest/run', type: 'POST', contentType: 'application/json', data: '{}'
        }).done(function(res) {
            const results = (res && res.results) || [];
            if (!results.length) {
                digestStatus('Nem ment ki üzenet.', false);
                return;
            }
            const text = results.map(function(r) {
                if (r.error) return r.diak + ' (hiba)';
                const idoszak = digestRovid(r.kezdo) + ' – ' + digestRovid(r.vege);
                return r.diak + ' (' + idoszak + ')';
            }).join(', ');
            const sent = (res && res.sent) || [];
            digestStatus('Elküldve: ' + text + '.', sent.length > 0);
        }).fail(function(xhr) {
            const msg = (xhr.responseJSON && xhr.responseJSON.message) || 'A küldés nem sikerült.';
            digestStatus(msg, false);
        });
    });
    $('#keresesInput').on('input', function() {
        const q = $(this).val().trim();
        clearTimeout(keresesTimer);
        $('#keresesElozmeny').toggleClass('d-none', q.length > 0);
        if (q.length < 2) {
            keresesTalalatok = [];
            keresesAktualis = -1;
            $('#keresesEredmeny').empty();
            if (!q) renderKeresesElozmeny();
            return;
        }
        keresesTimer = setTimeout(function() { keresesFuttat(q); }, 250);
    });
    $('#keresesInput').on('keydown', function(e) {
        if (e.key === 'ArrowDown' || e.key === 'ArrowUp') {
            if (!keresesTalalatok.length) return;
            e.preventDefault();
            const delta = e.key === 'ArrowDown' ? 1 : -1;
            keresesAktualis = (keresesAktualis + delta + keresesTalalatok.length)
                % keresesTalalatok.length;
            const $sorok = $('#keresesEredmeny .kereses-talalat');
            $sorok.removeClass('kereses-aktualis');
            const $sor = $sorok.filter('[data-idx="' + keresesAktualis + '"]')
                .addClass('kereses-aktualis');
            if ($sor.length && $sor[0].scrollIntoView) {
                $sor[0].scrollIntoView({block: 'nearest'});
            }
        } else if (e.key === 'Enter') {
            e.preventDefault();
            clearTimeout(keresesTimer);
            if (keresesAktualis >= 0 && keresesTalalatok[keresesAktualis]) {
                keresesElozmenyMent($(this).val());
                keresesTalalatMegnyit(keresesTalalatok[keresesAktualis]);
            } else {
                const q = $(this).val().trim();
                keresesFuttat(q);
                if (q.length >= 2) keresesElozmenyMent(q);
            }
        }
    });
    $('#keresesEredmeny').on('click', '.kereses-talalat', function() {
        const idx = Number($(this).data('idx'));
        $(this).addClass('kereses-villanas');
        keresesElozmenyMent($('#keresesInput').val());
        if (keresesTalalatok[idx]) keresesTalalatMegnyit(keresesTalalatok[idx]);
    });
    $('#keresesElozmeny').on('click', '.kereses-elozmeny', function() {
        const q = $(this).data('q') || '';
        $('#keresesInput').val(q);
        $('#keresesElozmeny').addClass('d-none');
        keresesFuttat(q);
    });

    // ── Sötét mód (Kaneo #86) ─────────────────────────────────────────────
    function applyTheme(theme) {
        const dark = theme === 'dark';
        document.documentElement.setAttribute('data-bs-theme', dark ? 'dark' : 'light');
        try { localStorage.setItem('kretaTheme', dark ? 'dark' : 'light'); } catch (e) {}
        $('#btnTheme i').toggleClass('fa-moon', !dark).toggleClass('fa-sun', dark);
        $('#btnTheme').attr('title', dark ? 'Világos mód' : 'Sötét mód');
    }

    let mentettTema = 'light';
    try { mentettTema = localStorage.getItem('kretaTheme') || 'light'; } catch (e) {}
    applyTheme(mentettTema);
    $('#btnTheme').on('click', function() {
        const most = document.documentElement.getAttribute('data-bs-theme');
        applyTheme(most === 'dark' ? 'light' : 'dark');
    });

    // ── Nyomtatásbarát heti órarend (Kaneo #86) ───────────────────────────
    const PRINT_NAPOK = [
        ['hétfő', 'Hétfő'], ['kedd', 'Kedd'], ['szerda', 'Szerda'],
        ['csütörtök', 'Csütörtök'], ['péntek', 'Péntek'], ['szombat', 'Szombat'],
        ['vasárnap', 'Vasárnap']
    ];

    function oraRendTabla(nev, rows) {
        // nap + kezdés szerinti cellák; a szinkron két hetet is hozhat -> dedupe
        const cellak = {};
        rows.forEach(function(r) {
            const nap = String(r.nap || '').toLowerCase();
            const kezdes = String(r.kezdo_idopont || '').slice(11, 16);
            if (!nap || !kezdes) return;
            const kulcs = nap + '|' + kezdes;
            if (!cellak[kulcs]) cellak[kulcs] = {};
            const tantargy = r.tantargy || '';
            if (!cellak[kulcs][tantargy]) {
                cellak[kulcs][tantargy] = { terem: r.terem || '', tanar: r.tanar || '' };
            }
        });
        const napok = PRINT_NAPOK.filter(function(p) {
            return rows.some(function(r) { return String(r.nap || '').toLowerCase() === p[0]; });
        });
        const idopontok = Array.from(new Set(
            Object.keys(cellak).map(function(k) { return k.split('|')[1]; }))).sort();

        let html = `<h3>${escapeHtml(nev)}</h3><table><thead><tr><th>Időpont</th>`;
        napok.forEach(function(p) { html += `<th>${escapeHtml(p[1])}</th>`; });
        html += '</tr></thead><tbody>';
        idopontok.forEach(function(ido) {
            html += `<tr><td class="print-idopont">${escapeHtml(ido)}</td>`;
            napok.forEach(function(p) {
                html += '<td>';
                const tantargyak = cellak[p[0] + '|' + ido] || {};
                Object.keys(tantargyak).forEach(function(t) {
                    const adat = tantargyak[t];
                    html += `<div class="print-tantargy">${escapeHtml(t)}</div>`;
                    if (adat.terem) html += `<div class="print-hely">${escapeHtml(adat.terem)}</div>`;
                });
                html += '</td>';
            });
            html += '</tr>';
        });
        return html + '</tbody></table>';
    }

    function nyomtatasiIdoszak() {
        // A nyomtatott táblázat mindig teljes hetet mutat, ezért a naptárban
        // éppen látszó nap/óra HETÉT vesszük (hétfő–vasárnap); naptár nélkül
        // az aktuális hetet.
        function hetKezdo(d) {
            const off = (d.getDay() + 6) % 7;   // hétfő = 0
            return new Date(d.getFullYear(), d.getMonth(), d.getDate() - off);
        }
        const alap = (orarendCalendar && orarendCalendar.view && orarendCalendar.view.currentStart)
            ? new Date(orarendCalendar.view.currentStart) : new Date();
        const kezdo = hetKezdo(alap);
        const zaro = new Date(kezdo);
        zaro.setDate(zaro.getDate() + 6);
        return {kezdo: fmtIsoToHu(fmtDate(kezdo)), zaro: fmtIsoToHu(fmtDate(zaro))};
    }

    function nyomtatasiOrarend() {
        const diak = $('#orarendFilterDiak').val() || $('#filterDiak').val() || '';
        const nev = diak || 'Minden gyermek';
        const idoszak = nyomtatasiIdoszak();
        const eredetiCim = document.title;
        $.getJSON(`/api/orarend?diak=${encodeURIComponent(diak)}`, function(rows) {
            const $c = $('#printOrarend').empty();
            $c.append('<h2>SuliHub – Órarend</h2>');
            $c.append(`<div class="print-meta">${escapeHtml(nev)} · ` +
                      `${escapeHtml(idoszak.kezdo)} – ${escapeHtml(idoszak.zaro)}</div>`);
            if (!rows || !rows.length) {
                $c.append('<p>Nincs megjeleníthető óra.</p>');
            } else {
                const diakok = {};
                rows.forEach(function(r) {
                    const dnev = r.diak_nev || 'Ismeretlen';
                    (diakok[dnev] = diakok[dnev] || []).push(r);
                });
                Object.keys(diakok).sort().forEach(function(dnev) {
                    $c.append(oraRendTabla(dnev, diakok[dnev]));
                });
            }
            // A böngésző fejléce a document.title-t nyomtatja (Kaneo #114).
            document.title = `SuliHub - Órarend - ${nev} - ${idoszak.kezdo} - ${idoszak.zaro}`;
            const visszaallit = function() {
                document.title = eredetiCim;
                window.removeEventListener('afterprint', visszaallit);
            };
            window.addEventListener('afterprint', visszaallit);
            setTimeout(function() { window.print(); }, 60);
            setTimeout(visszaallit, 5000);   // biztonsági visszaállítás
        }).fail(function() {
            alert('Az órarend nem tölthető be.');
        });
    }

    $('#btnOrarendNyomtat').on('click', nyomtatasiOrarend);

    // ── Kitűzött események (Kaneo #86) ────────────────────────────────────
    function frissitKedvencIkonok() {
        $('.btn-kedvenc').each(function() {
            const kulcs = $(this).data('kulcs');
            const benne = kulcs && kedvencKulcsok.has(kulcs);
            $(this).find('i').toggleClass('fa-solid', !!benne).toggleClass('fa-regular', !benne);
            $(this).attr('title', benne ? 'Kitűzés levétele' : 'Kitűzés a dashboardra');
        });
    }

    function renderKedvencek(list) {
        const $lista = $('#kedvencLista').empty();
        if (!list || !list.length) {
            $('#kedvencPanel').addClass('d-none');
            return;
        }
        $('#kedvencPanel').removeClass('d-none');
        list.forEach(function(e) {
            const cim = [e.tantargy, e.tema || e.cim].filter(Boolean).join(' – ') || e.esemeny_tipus;
            const datum = e.hatarido || e.bej_datum;
            const jegyzet = e.megjegyzes
                ? `<span class="kedvenc-jegyzet small text-muted ms-2">${escapeHtml(e.megjegyzes)}</span>`
                : '';
            $lista.append(`<div class="list-group-item d-flex align-items-center justify-content-between py-1 px-2 kedvenc-sor"
                    draggable="true" data-kulcs="${escapeHtml(e.kulcs)}">
                <span class="kedvenc-fogantyú me-2" title="Húzd a sorrendezéshez">☰</span>
                <button type="button" class="btn btn-link p-0 text-start text-decoration-none flex-grow-1 kedvenc-ugras"
                        data-diak="${escapeHtml(e.diak_nev)}" data-tipus="${escapeHtml(e.esemeny_tipus)}"
                        data-tantargy="${escapeHtml(e.tantargy)}">
                    <span class="badge bg-warning text-dark me-1">${escapeHtml(e.esemeny_tipus)}</span>
                    <span class="fw-semibold">${escapeHtml(cim)}</span>
                    <span class="text-muted small ms-1">${escapeHtml(e.diak_nev)}</span>
                    ${datum ? `<span class="text-muted small ms-2">${escapeHtml(datum)}</span>` : ''}
                </button>
                ${jegyzet}
                <button type="button" class="btn btn-sm btn-link text-secondary p-0 ms-2 kedvenc-jegyzet-szerk"
                        data-kulcs="${escapeHtml(e.kulcs)}" data-jegyzet="${escapeHtml(e.megjegyzes || '')}"
                        title="Megjegyzés szerkesztése">
                    <i class="fa-regular fa-pen-to-square"></i>
                </button>
                <button type="button" class="btn btn-sm btn-link text-warning p-0 ms-2 kedvenc-torol"
                        data-kulcs="${escapeHtml(e.kulcs)}" title="Kitűzés levétele">
                    <i class="fa-solid fa-star"></i>
                </button>
            </div>`);
        });
    }

    function betoltKedvencek() {
        $.getJSON('/api/kedvencek', function(res) {
            kedvencKulcsok = new Set(res.kulcsok || []);
            renderKedvencek(res.esemenyek || []);
            frissitKedvencIkonok();
        });
    }

    function kedvencValtas(kulcs) {
        if (!kulcs) return;
        const akcio = kedvencKulcsok.has(kulcs) ? 'remove' : 'add';
        $.ajax({
            url: '/api/kedvencek',
            method: 'POST',
            contentType: 'application/json',
            data: JSON.stringify({kulcs: kulcs, akcio: akcio})
        }).done(function(res) {
            kedvencKulcsok = new Set(res.kulcsok || []);
            renderKedvencek(res.esemenyek || []);
            frissitKedvencIkonok();
        });
    }

    $('#esemenyekTable').on('click', '.btn-kedvenc', function(e) {
        e.stopPropagation();
        kedvencValtas($(this).data('kulcs'));
    });

    $('#kedvencLista').on('click', '.kedvenc-ugras', function() {
        goToEvents({
            diak: $(this).data('diak') || '', tipus: $(this).data('tipus') || '',
            tantargy: $(this).data('tantargy') || '',
            status: '', kezdo: '', zaro: '', hatKezdo: '', hatZaro: ''
        });
    });

    $('#kedvencLista').on('click', '.kedvenc-torol', function(e) {
        e.stopPropagation();
        kedvencValtas($(this).data('kulcs'));
    });

    // Megjegyzés a kitűzött tételhez (Kaneo #108).
    $('#kedvencLista').on('click', '.kedvenc-jegyzet-szerk', function(e) {
        e.stopPropagation();
        const kulcs = $(this).data('kulcs');
        const jelenlegi = $(this).data('jegyzet') || '';
        const uj = window.prompt('Megjegyzés a kitűzött tételhez (max. 200 karakter):', jelenlegi);
        if (uj === null) return;
        $.ajax({
            url: '/api/kedvencek',
            method: 'POST',
            contentType: 'application/json',
            data: JSON.stringify({akcio: 'note', kulcs: kulcs, megjegyzes: uj})
        }).done(function(res) {
            renderKedvencek(res.esemenyek || []);
        });
    });

    // Húzásos sorrendezés (Kaneo #108) — a sorrend app_meta-ba mentve.
    $('#kedvencLista').on('dragstart', '.kedvenc-sor', function(e) {
        $(this).addClass('kedvenc-drag');
        try {
            e.originalEvent.dataTransfer.effectAllowed = 'move';
            e.originalEvent.dataTransfer.setData('text/plain', $(this).data('kulcs') || '');
        } catch (err) { /* régi böngésző */ }
    });
    $('#kedvencLista').on('dragover', '.kedvenc-sor', function(e) {
        e.preventDefault();
        const $sor = $(this);
        const $drag = $('.kedvenc-sor.kedvenc-drag');
        if (!$drag.length || $drag[0] === $sor[0]) return;
        const y = e.originalEvent.clientY - $sor[0].getBoundingClientRect().top;
        if (y > $sor.outerHeight() / 2) $drag.insertAfter($sor);
        else $drag.insertBefore($sor);
    });
    $('#kedvencLista').on('drop', '.kedvenc-sor', function(e) { e.preventDefault(); });
    $('#kedvencLista').on('dragend', '.kedvenc-sor', function() {
        $(this).removeClass('kedvenc-drag');
        const kulcsok = $('#kedvencLista .kedvenc-sor').map(function() {
            return $(this).data('kulcs');
        }).get();
        $.ajax({
            url: '/api/kedvencek',
            method: 'POST',
            contentType: 'application/json',
            data: JSON.stringify({akcio: 'order', kulcsok: kulcsok})
        }).done(function(res) {
            kedvencKulcsok = new Set(res.kulcsok || []);
            renderKedvencek(res.esemenyek || []);
        });
    });

    betoltKedvencek();
});
