const topology  = JSON.parse(localStorage.getItem('topology') || '{}');
const filename  = localStorage.getItem('filename') || '';
const fileType  = localStorage.getItem('file_type') || '';

const _sp = window.MTDZ_PAGES || {};
if (!localStorage.getItem('session_id')) {
  window.location.href = (_sp.index || 'index.html');
}

// ── Page header ────────────────────────────────────────────────────────────────

// Show "no trend data" banner only for pure system info files
if (fileType === 'sysinfo') {
  document.getElementById('sysinfo-banner').style.display = '';
}

// Always show monitoring nav links for mtdz/mtlz files
if (fileType === 'mtdz' || fileType === 'mtlz') {
  document.getElementById('link-viewer').style.display = '';
  document.getElementById('link-report').style.display = '';
}

const systems = topology.systems || [];
if (topology.monitor_name) {
  document.getElementById('map-title').textContent =
    `System Configuration Map — ${topology.monitor_name}`;
}

if (systems.length === 0) {
  document.getElementById('topo-svg').style.display = 'none';
  document.getElementById('no-systems-msg').style.display = '';
} else {
  renderTopology(systems);
}

// ── SVG renderer ───────────────────────────────────────────────────────────────
function renderTopology(systems) {
  const NS = 'http://www.w3.org/2000/svg';

  // ── Dimensions ──────────────────────────────────────────────────────────────
  const OC_W    = 90,  OC_H  = 26;
  const OS_GAP  = 10;   // gap between OC right edge and OS left edge
  const BC_W    = 90;
  const BC_HDR  = 28;   // BC label area height at top of box
  const PORT_H  = 30;   // height per port row
  const BC_BOT  = 6;    // bottom padding inside BC box
  const IC_W    = 90,  IC_H  = 22;
  const IC_GAP  = 6;    // vertical gap between stacked ICs sharing a BC port
  const IC_PAD  = 4;    // top/bottom padding inside a multi-IC port slot
  const CONN_W  = 44;   // horizontal gap: BC right edge → IC left edge
  const CAP_LEN = 28,  CAP_SQ = 7;   // empty-port cap: line length + square side
  const PAD_X   = 24,  PAD_TOP = 20;
  const SYS_GAP = 32;
  const OC_BC_V = 16;   // vertical gap: OC bottom → BC top
  const BS_GAP  = 12;   // vertical gap: main BC bottom → Sub BC top

  // ── Helpers ─────────────────────────────────────────────────────────────────
  function el(tag, attrs, text) {
    const e = document.createElementNS(NS, tag);
    for (const [k, v] of Object.entries(attrs)) e.setAttribute(k, v);
    if (text !== undefined) e.textContent = text;
    return e;
  }

  function addTitle(g, lines) {
    const t = document.createElementNS(NS, 'title');
    t.textContent = lines.filter(Boolean).join('\n');
    g.appendChild(t);
  }

  // Highest port number used by this system (including twin ports)
  function maxUsedPort(sys) {
    let m = 0;
    for (const ic of sys.ics) {
      if (ic.port      != null) m = Math.max(m, ic.port);
      if (ic.twin_port != null) m = Math.max(m, ic.twin_port);
    }
    return m;
  }

  // Total BC port count: prefer backend-provided value, else round up to
  // nearest standard Mitsubishi BC size (8 / 12 / 16 / 24 / 32).
  function bcPortCount(sys) {
    if (sys.bc.port_count > 0) return sys.bc.port_count;
    const m = maxUsedPort(sys);
    for (const s of [8, 12, 16, 24, 32]) { if (s >= m) return s; }
    return m;
  }

  function bsPortCount(bs) {
    if (bs.port_count > 0) return bs.port_count;
    let m = 0;
    for (const ic of bs.ics || []) {
      if (ic.port      != null) m = Math.max(m, ic.port);
      if (ic.twin_port != null) m = Math.max(m, ic.twin_port);
    }
    for (const s of [8, 12, 16, 24, 32]) { if (s >= m) return s; }
    return Math.max(m, 1);
  }

  // Vertical pixels for one port row given its IC count.
  // Returns PORT_H for 0 or 1 ICs (visually identical to pre-stack behavior);
  // grows linearly when multiple ICs share a port.
  function slotHeight(nIc) {
    if (nIc <= 1) return PORT_H;
    return nIc * IC_H + (nIc - 1) * IC_GAP + IC_PAD * 2;
  }

  // Layout per BC/BS port: bucket ICs by primary port, resolve twin markers,
  // compute per-slot heights and cumulative offsets. Slots are 0-indexed
  // (slots[0] is port 1). Real ICs always win over a twin marker on the same row.
  function buildPortLayout(ics, nPorts) {
    const bucket = {};
    const twinSet = new Set();
    for (const ic of (ics || [])) {
      if (ic.port != null) (bucket[ic.port] ||= []).push(ic);
      if (ic.twin_port != null) twinSet.add(ic.twin_port);
    }
    const slots = new Array(nPorts);
    let totalH = 0;
    for (let p = 1; p <= nPorts; p++) {
      const portIcs = (bucket[p] || []).slice().sort((a, b) => a.address - b.address);
      const height = slotHeight(portIcs.length);
      slots[p - 1] = {
        ics: portIcs,
        twin: twinSet.has(p) && portIcs.length === 0,
        height,
        topRel: totalH,
      };
      totalH += height;
    }
    return { totalH, slots };
  }

  // Append one IC box (rect + label + tooltip) at (icLeftX, icCy).
  function appendIcBox(svgRoot, ic, icLeftX, icCy) {
    const icG = document.createElementNS(NS, 'g');
    addTitle(icG, [ic.model, ic.tag, ic.capacity ? `${ic.capacity} MBH` : '']);
    icG.appendChild(el('rect', {
      x: icLeftX, y: icCy - IC_H / 2, width: IC_W, height: IC_H,
      class: 'unit-box ic-box',
    }));
    icG.appendChild(el('text', {
      x: icLeftX + IC_W / 2, y: icCy, class: 'unit-label-single',
    }, `IC ${ic.address.toString().padStart(2, '0')}`));
    svgRoot.appendChild(icG);
  }

  // Draw all port rows (label, pipes, ICs, caps) for a BC or BS.
  // Centralized so main BC and Sub-BCs share identical geometry rules.
  // For N >= 2 ICs sharing a port, draws a manifold: trunk → vertical riser → per-IC stub.
  function renderPortRows({ svgRoot, layout, hostX, hostY, lineX0 }) {
    for (let p = 1; p <= layout.slots.length; p++) {
      const slot = layout.slots[p - 1];
      const slotCenterY = hostY + BC_HDR + slot.topRel + slot.height / 2;

      // Port number label, right-aligned inside BC/BS, centered on slot.
      svgRoot.appendChild(el('text', {
        x: hostX + BC_W - 6, y: slotCenterY,
        'text-anchor': 'end', 'dominant-baseline': 'middle',
        'font-size': '10', fill: 'rgba(255,255,255,0.45)',
      }, String(p)));

      const n = slot.ics.length;

      if (n === 0 && slot.twin) {
        svgRoot.appendChild(el('line', {
          x1: lineX0, y1: slotCenterY,
          x2: lineX0 + CONN_W * 0.55, y2: slotCenterY,
          stroke: 'rgba(42,122,82,0.45)', 'stroke-width': '1',
          'stroke-dasharray': '3,3',
        }));
        svgRoot.appendChild(el('text', {
          x: lineX0 + CONN_W * 0.55 + 4, y: slotCenterY,
          'dominant-baseline': 'middle', 'font-size': '9',
          fill: 'rgba(255,255,255,0.25)',
        }, 'twin'));

      } else if (n === 0) {
        svgRoot.appendChild(el('line', {
          x1: lineX0, y1: slotCenterY,
          x2: lineX0 + CAP_LEN, y2: slotCenterY, class: 'port-cap-line',
        }));
        svgRoot.appendChild(el('rect', {
          x: lineX0 + CAP_LEN, y: slotCenterY - CAP_SQ / 2,
          width: CAP_SQ, height: CAP_SQ, class: 'port-cap-sq',
        }));

      } else if (n === 1) {
        const ic = slot.ics[0];
        svgRoot.appendChild(el('line', {
          x1: lineX0, y1: slotCenterY,
          x2: lineX0 + CONN_W, y2: slotCenterY, class: 'connect-line',
        }));
        appendIcBox(svgRoot, ic, lineX0 + CONN_W, slotCenterY);

      } else {
        const firstIcCy = hostY + BC_HDR + slot.topRel + IC_PAD + IC_H / 2;
        const lastIcCy  = firstIcCy + (n - 1) * (IC_H + IC_GAP);
        const riserX    = lineX0 + CONN_W / 2;

        svgRoot.appendChild(el('line', {
          x1: lineX0, y1: slotCenterY,
          x2: riserX, y2: slotCenterY, class: 'connect-line',
        }));
        svgRoot.appendChild(el('line', {
          x1: riserX, y1: firstIcCy,
          x2: riserX, y2: lastIcCy, class: 'connect-line',
        }));
        for (let i = 0; i < n; i++) {
          const icCy = firstIcCy + i * (IC_H + IC_GAP);
          svgRoot.appendChild(el('line', {
            x1: riserX, y1: icCy,
            x2: lineX0 + CONN_W, y2: icCy, class: 'connect-line',
          }));
          appendIcBox(svgRoot, slot.ics[i], lineX0 + CONN_W, icCy);
        }
      }
    }
  }

  // System width — BC+connection+IC for systems with a BC; OC/IC width otherwise
  function sysW(sys) {
    return sys.bc ? BC_W + CONN_W + IC_W : Math.max(OC_W, IC_W);
  }

  // System content height (excluding outer PAD_TOP)
  function sysH(sys) {
    if (sys.bc) {
      let h = OC_H + OC_BC_V + BC_HDR
            + buildPortLayout(sys.ics, bcPortCount(sys)).totalH + BC_BOT;
      for (const bs of (sys.bss || [])) {
        h += BS_GAP + BC_HDR
           + buildPortLayout(bs.ics || [], bsPortCount(bs)).totalH + BC_BOT;
      }
      return h;
    }
    return OC_H + OC_BC_V + Math.max(sys.ics.length, 1) * PORT_H;
  }

  // ── Canvas size ─────────────────────────────────────────────────────────────
  const totalW = PAD_X * 2
               + systems.reduce((s, sys) => s + sysW(sys), 0)
               + SYS_GAP * Math.max(systems.length - 1, 0);
  const totalH = PAD_TOP * 2 + Math.max(...systems.map(sysH));

  const svg = document.getElementById('topo-svg');
  svg.setAttribute('width',   totalW);
  svg.setAttribute('height',  totalH);
  svg.setAttribute('viewBox', `0 0 ${totalW} ${totalH}`);

  let curX = PAD_X;

  for (let si = 0; si < systems.length; si++) {
    const sys    = systems[si];
    const sw     = sysW(sys);
    const ocCx   = curX + BC_W / 2;       // OC and BC share the same centre-x
    const ocY    = PAD_TOP;
    const bcY    = PAD_TOP + OC_H + OC_BC_V;
    const nPorts = sys.bc ? bcPortCount(sys) : 0;
    const bcLayout = sys.bc ? buildPortLayout(sys.ics, nPorts) : null;
    const bh     = bcLayout ? BC_HDR + bcLayout.totalH + BC_BOT : 0;

    // ── OC box ───────────────────────────────────────────────────────────────
    const ocG = document.createElementNS(NS, 'g');
    addTitle(ocG, [sys.oc.model, sys.oc.tag, sys.oc.capacity ? `${sys.oc.capacity} MBH` : '']);
    ocG.appendChild(el('rect', {
      x: ocCx - OC_W / 2, y: ocY, width: OC_W, height: OC_H,
      class: 'unit-box oc-box',
    }));
    ocG.appendChild(el('text', {
      x: ocCx, y: ocY + OC_H / 2, class: 'unit-label-single',
    }, `OC ${sys.oc.address.toString().padStart(2, '0')}`));
    svg.appendChild(ocG);

    // ── OS box (twinned slave — same row as OC, to its right) ────────────────
    if (sys.os) {
      const osX = ocCx + OC_W / 2 + OS_GAP;
      const osCx = osX + OC_W / 2;
      const osG = document.createElementNS(NS, 'g');
      addTitle(osG, [sys.os.model, sys.os.tag, sys.os.capacity ? `${sys.os.capacity} MBH` : '']);
      osG.appendChild(el('rect', {
        x: osX, y: ocY, width: OC_W, height: OC_H,
        class: 'unit-box os-box',
      }));
      osG.appendChild(el('text', {
        x: osCx, y: ocY + OC_H / 2, class: 'unit-label-single',
      }, `OS ${sys.os.address.toString().padStart(2, '0')}`));
      svg.appendChild(osG);
    }

    if (sys.bc) {
      // ── OC → BC connector ─────────────────────────────────────────────────
      svg.appendChild(el('line', {
        x1: ocCx, y1: ocY + OC_H, x2: ocCx, y2: bcY, class: 'connect-line',
      }));

      // ── BC box ────────────────────────────────────────────────────────────
      const bcG = document.createElementNS(NS, 'g');
      addTitle(bcG, [sys.bc.model, sys.bc.tag]);
      bcG.appendChild(el('rect', {
        x: curX, y: bcY, width: BC_W, height: bh, class: 'unit-box bc-box',
      }));
      bcG.appendChild(el('text', {
        x: ocCx, y: bcY + BC_HDR / 2, class: 'unit-label-single',
      }, `BC ${sys.bc.address.toString().padStart(2, '0')}`));
      // Divider below BC label
      bcG.appendChild(el('line', {
        x1: curX + 6, y1: bcY + BC_HDR - 1,
        x2: curX + BC_W - 6, y2: bcY + BC_HDR - 1,
        stroke: 'rgba(255,255,255,0.2)', 'stroke-width': '0.75',
      }));
      svg.appendChild(bcG);

      // ── Port rows ─────────────────────────────────────────────────────────
      const lineX0 = curX + BC_W;
      renderPortRows({ svgRoot: svg, layout: bcLayout, hostX: curX, hostY: bcY, lineX0 });

      // ── Sub BCs (BS) ──────────────────────────────────────────────────────
      let prevBcBottom = bcY + bh;
      for (const bs of (sys.bss || [])) {
        const bsPortN = bsPortCount(bs);
        const bsLayout = buildPortLayout(bs.ics || [], bsPortN);
        const bsh      = BC_HDR + bsLayout.totalH + BC_BOT;
        const bsY      = prevBcBottom + BS_GAP;

        // Connector from main BC bottom to Sub BC top
        svg.appendChild(el('line', {
          x1: ocCx, y1: prevBcBottom, x2: ocCx, y2: bsY, class: 'connect-line',
        }));

        // BS box
        const bsG = document.createElementNS(NS, 'g');
        addTitle(bsG, [bs.model, bs.tag]);
        bsG.appendChild(el('rect', {
          x: curX, y: bsY, width: BC_W, height: bsh, class: 'unit-box bc-box',
        }));
        bsG.appendChild(el('text', {
          x: ocCx, y: bsY + BC_HDR / 2, class: 'unit-label-single',
        }, `BS ${bs.address.toString().padStart(2, '0')}`));
        bsG.appendChild(el('line', {
          x1: curX + 6, y1: bsY + BC_HDR - 1,
          x2: curX + BC_W - 6, y2: bsY + BC_HDR - 1,
          stroke: 'rgba(255,255,255,0.2)', 'stroke-width': '0.75',
        }));
        svg.appendChild(bsG);

        renderPortRows({ svgRoot: svg, layout: bsLayout, hostX: curX, hostY: bsY, lineX0 });

        prevBcBottom = bsY + bsh;
      }

    } else {
      // ── No BC: ICs chain directly below OC ───────────────────────────────
      let prevBottom = ocY + OC_H;
      for (let i = 0; i < sys.ics.length; i++) {
        const ic    = sys.ics[i];
        const icCy  = bcY + (i + 0.5) * PORT_H;
        const icTop = icCy - IC_H / 2;
        svg.appendChild(el('line', {
          x1: ocCx, y1: prevBottom, x2: ocCx, y2: icTop, class: 'connect-line',
        }));
        const icG = document.createElementNS(NS, 'g');
        addTitle(icG, [ic.model, ic.tag, ic.capacity ? `${ic.capacity} MBH` : '']);
        icG.appendChild(el('rect', {
          x: ocCx - IC_W / 2, y: icTop, width: IC_W, height: IC_H,
          class: 'unit-box ic-box',
        }));
        icG.appendChild(el('text', {
          x: ocCx, y: icCy, class: 'unit-label-single',
        }, `IC ${ic.address.toString().padStart(2, '0')}`));
        svg.appendChild(icG);
        prevBottom = icCy + IC_H / 2;
      }
    }

    // ── System divider ────────────────────────────────────────────────────────
    if (si < systems.length - 1) {
      const divX = curX + sw + SYS_GAP / 2;
      svg.appendChild(el('line', {
        x1: divX, y1: PAD_TOP, x2: divX, y2: totalH - PAD_TOP,
        class: 'sys-divider',
      }));
    }

    curX += sw + SYS_GAP;
  }
}
