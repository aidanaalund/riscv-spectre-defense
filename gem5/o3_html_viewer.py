
#!/usr/bin/env python3
"""Interactive HTML viewer for gem5 O3PipeView traces.

Usage:
python3 o3_html_viewer.py m5out/lfence_trace.out -o m5out/lfence_view.html
"""

import argparse
import json
import re
from pathlib import Path

FETCH = re.compile(
    r'^O3PipeView:fetch:(\d+):([^:]+):(\d+):(\d+):(.*)$'
)

STAGE = re.compile(
    r'^O3PipeView:(decode|rename|dispatch|issue|complete|retire):(\d+)'
)

STAGES = [
    "fetch", "decode", "rename", "dispatch",
    "issue", "complete", "retire"
]


def parse_trace(path):
    records = []
    current = None

    with open(path, "r", errors="replace") as f:
        for line in f:
            line = line.strip()

            match = FETCH.match(line)

            if match:
                if current is not None:
                    records.append(current)

                tick, pc, upc, seq, instruction = match.groups()

                current = {
                    "seq": int(seq),
                    "pc": pc,
                    "upc": int(upc),
                    "instruction": instruction.strip(),
                    "fetch": int(tick)
                }

                continue

            match = STAGE.match(line)

            if match and current is not None:
                current[match.group(1)] = int(match.group(2))

    if current is not None:
        records.append(current)

    # IMPORTANT: Preserve program sequence ordering.
    records.sort(key=lambda d: d["seq"])

    return records


HTML = r'''<!doctype html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">

<title>gem5 O3 Pipeline Viewer</title>

<style>
:root {
    color-scheme: dark;
    font-family: system-ui, Arial, sans-serif;
    background: #0b1220;
    color: #e5e7eb;
}

* { box-sizing: border-box; }

body { margin: 0; }

header {
    padding: 16px 22px;
    background: #111827;
    border-bottom: 1px solid #334155;
}

h1 {
    font-size: 20px;
    margin: 0 0 7px;
}

.subtitle {
    color: #94a3b8;
    font-size: 12px;
    line-height: 1.6;
}

.controls {
    display: flex;
    align-items: center;
    flex-wrap: wrap;
    gap: 12px;
    margin-top: 14px;
}

input, button, select {
    background: #1e293b;
    border: 1px solid #475569;
    color: #e5e7eb;
    border-radius: 6px;
    padding: 7px;
}

input[type=search] { width: 250px; }

button { cursor: pointer; }
button:hover { background: #334155; }

main { padding: 14px 20px; }

.legend {
    display: flex;
    flex-wrap: wrap;
    gap: 14px;
    font-size: 12px;
    margin-bottom: 12px;
}

.dot {
    display: inline-block;
    width: 11px;
    height: 11px;
    border-radius: 2px;
    margin-right: 5px;
}

.viewer {
    border: 1px solid #334155;
    border-radius: 8px;
    overflow: hidden;
    background: #0f172a;
}

.axis {
    display: block;
    width: 100%;
    height: 50px;
    background: #172235;
}

#topAxis {
    border-bottom: 1px solid #334155;
}

#bottomAxis {
    border-top: 1px solid #334155;
}

#viewport {
    height: 60vh;
    overflow: auto;
    position: relative;
    background: #0f172a;
}

#canvas {
    display: block;
}

#details {
    background: #111827;
    border: 1px solid #334155;
    border-radius: 7px;
    margin-top: 12px;
    padding: 12px;
    font-size: 13px;
    white-space: pre-wrap;
    line-height: 1.6;
}

#tip {
    position: fixed;
    display: none;
    z-index: 100;
    pointer-events: none;
    background: #020617;
    border: 1px solid #64748b;
    border-radius: 7px;
    padding: 10px;
    font-size: 12px;
    line-height: 1.6;
    max-width: 340px;
    box-shadow: 0 7px 35px #0008;
}

.muted { color: #94a3b8; }
</style>
</head>

<body>

<header>
<h1>gem5 O3 Pipeline Viewer</h1>

<div class="subtitle">
Top axis: CPU cycles · Bottom axis: simulation ticks
<br>
Mouse wheel: zoom at cursor · Shift + wheel: horizontal pan ·
Click instruction: inspect timestamps
<br>
Instructions displayed in dynamic sequence-number order.
</div>

<div class="controls">

<label>
Find instruction
<input id="search" type="search"
       placeholder="lfence, ld, addi, PC, seq...">
</label>

<label>
<input id="committed" type="checkbox" checked>
Retired only
</label>

<label>
Rows
<select id="limit">
<option value="100">100</option>
<option value="500" selected>500</option>
<option value="2000">2000</option>
<option value="10000">10000</option>
</select>
</label>

<label>
Ticks / CPU cycle
<input id="ticksPerCycle"
       type="number"
       min="1"
       value="500"
       style="width:90px">
</label>

<button id="zin">Zoom in +</button>
<button id="zout">Zoom out −</button>
<button id="fit">Fit time</button>

<span id="count" class="subtitle"></span>

</div>
</header>

<main>

<div class="legend" id="legend"></div>

<div class="viewer">

<canvas id="topAxis" class="axis"></canvas>

<div id="viewport">
    <canvas id="canvas"></canvas>
</div>

<canvas id="bottomAxis" class="axis"></canvas>

</div>

<div id="details" class="muted">
Click an instruction to inspect its pipeline timestamps.
</div>

</main>

<div id="tip"></div>

<script>
const DATA = __RECORDS__;

const STAGES = [
    'fetch', 'decode', 'rename', 'dispatch',
    'issue', 'complete', 'retire'
];

const COLORS = [
    '#4d9de0',
    '#68b0ab',
    '#a78bfa',
    '#eab308',
    '#fb923c',
    '#f472b6',
    '#34d399'
];

const VP = document.getElementById('viewport');
const CV = document.getElementById('canvas');
const CT = CV.getContext('2d');

const TOP_AXIS = document.getElementById('topAxis');
const BOTTOM_AXIS = document.getElementById('bottomAxis');

const TIP = document.getElementById('tip');

const ROW = 27;
const LEFT = 340;
const RIGHT = 70;

let filtered = [];
let origin = 0;
let maxTick = 1;
let scale = 0.01;
let selected = null;

let segments = [];

function number(n) {
    return Number(n).toLocaleString('en-US', {
        maximumFractionDigits: 3
    });
}

function ticksPerCycle() {
    return Math.max(
        1,
        Number(document.getElementById('ticksPerCycle').value) || 500
    );
}

document.getElementById('legend').innerHTML =
    STAGES.map((name, i) =>
        `<span><i class="dot" style="background:${COLORS[i]}"></i>${name}</span>`
    ).join('') +
    '<span class="muted">Gray = elapsed time between events</span>';


function filterRecords() {

    const q = document.getElementById('search')
        .value.trim().toLowerCase();

    const committed =
        document.getElementById('committed').checked;

    let matches = DATA.filter(d => {

        if (committed && !(d.retire > 0)) {
            return false;
        }

        if (!q) return true;

        return (
            `${d.instruction} ${d.pc} ${d.seq}`
                .toLowerCase().includes(q)
        );
    });

    // Preserve instruction program/sequence order.
    matches.sort((a, b) => a.seq - b.seq);

    const limit = Number(
        document.getElementById('limit').value
    );

    filtered = matches.slice(0, limit);

    const times = [];

    for (const d of filtered) {
        for (const s of STAGES) {
            if (d[s] > 0) times.push(d[s]);
        }
    }

    origin = times.length ? Math.min(...times) : 0;
    maxTick = times.length ? Math.max(...times) : origin + 1;

    document.getElementById('count').textContent =
        `${filtered.length.toLocaleString()} shown / ` +
        `${matches.length.toLocaleString()} matches / ` +
        `${DATA.length.toLocaleString()} total`;

    fitTime();
}


// Convert a simulation tick to a canvas coordinate.
function tickToX(t) {
    return LEFT + (t - origin) * scale;
}


// Choose readable time-axis increments.
function niceStep(raw) {

    const p = Math.pow(
        10,
        Math.floor(Math.log10(Math.max(raw, 0.000001)))
    );

    return (
        [1, 2, 5, 10]
            .map(n => n * p)
            .find(n => n >= raw) || 10 * p
    );
}


// Draw a synchronized fixed axis.
// mode = cycles or ticks
function drawAxis(canvas, mode) {

    const width = VP.clientWidth;
    const height = 50;

    const ratio = window.devicePixelRatio || 1;

    canvas.width = Math.round(width * ratio);
    canvas.height = Math.round(height * ratio);

    canvas.style.width = width + 'px';
    canvas.style.height = height + 'px';

    const ctx = canvas.getContext('2d');
    ctx.setTransform(ratio, 0, 0, ratio, 0, 0);

    ctx.fillStyle = '#172235';
    ctx.fillRect(0, 0, width, height);

    ctx.font = '12px Consolas, monospace';

    const tpc = ticksPerCycle();

    const unit = mode === 'cycles' ? tpc : 1;

    const label =
        mode === 'cycles'
            ? `CPU cycles (${number(tpc)} ticks/cycle)`
            : 'Simulation ticks';

    ctx.fillStyle = '#e2e8f0';
    ctx.fillText(label, 12, 15);

    // Desired interval between labels: ~115 pixels.
    const stepUnits = niceStep(
        115 / (scale * unit)
    );

    const stepTicks = stepUnits * unit;

    // Visible simulation-time range.
    const firstVisible =
        origin + (VP.scrollLeft - LEFT) / scale;

    const lastVisible =
        origin +
        (VP.scrollLeft + width - LEFT) / scale;

    const first =
        Math.ceil(firstVisible / stepTicks) * stepTicks;

    ctx.strokeStyle = '#475569';
    ctx.fillStyle = '#94a3b8';

    let count = 0;

    for (
        let t = first;
        t <= lastVisible && count < 1000;
        t += stepTicks, count++
    ) {

        const x = tickToX(t) - VP.scrollLeft;

        if (x < 0 || x > width) continue;

        ctx.beginPath();
        ctx.moveTo(x, 22);
        ctx.lineTo(x, 29);
        ctx.stroke();

        ctx.fillText(
            number(t / unit),
            x + 3,
            43
        );
    }
}


function drawAxes() {
    drawAxis(TOP_AXIS, 'cycles');
    drawAxis(BOTTOM_AXIS, 'ticks');
}


// Draw the instruction timeline.
function draw() {

    const width = Math.max(
        VP.clientWidth,
        Math.ceil(
            LEFT + (maxTick - origin) * scale + RIGHT
        )
    );

    const height = Math.max(
        VP.clientHeight,
        filtered.length * ROW + 20
    );

    CV.width = width;
    CV.height = height;

    CT.clearRect(0, 0, width, height);

    CT.font =
        '12px ui-monospace,Consolas,monospace';

    segments = [];

    // Background
    CT.fillStyle = '#0f172a';
    CT.fillRect(0, 0, width, height);

    // Vertical grid
    const step = niceStep(115 / scale);

    let count = 0;

    for (
        let t = Math.ceil(origin / step) * step;
        t <= maxTick && count < 10000;
        t += step, count++
    ) {

        const x = tickToX(t);

        CT.strokeStyle = '#263448';

        CT.beginPath();
        CT.moveTo(x, 0);
        CT.lineTo(x, height);
        CT.stroke();
    }

    // Instruction rows
    filtered.forEach((d, i) => {

        const y = i * ROW;

        if (i % 2 === 0) {
            CT.fillStyle = '#111d30';
            CT.fillRect(0, y, width, ROW);
        }

        if (selected === d.seq) {
            CT.fillStyle = '#24395a';
            CT.fillRect(0, y, width, ROW);
        }

        CT.fillStyle = '#e2e8f0';

        CT.fillText(
            String(d.seq).padStart(5),
            10,
            y + 18
        );

        CT.fillStyle = '#9cb5d3';
        CT.fillText(d.pc, 62, y + 18);

        let instruction = d.instruction;

        if (instruction.length > 28) {
            instruction = instruction.slice(0, 27) + '…';
        }

        CT.fillStyle =
            instruction.toLowerCase().includes('lfence')
                ? '#fbbf24'
                : '#e2e8f0';

        CT.fillText(
            instruction,
            170,
            y + 18
        );

        // Valid pipeline events
        const events = STAGES
            .map((stage, j) => ({
                stage,
                j,
                time: d[stage]
            }))
            .filter(e => e.time > 0);

        events.forEach((e, k) => {

            const next = events[k + 1];

            const x = tickToX(e.time);

            const end = next
                ? tickToX(next.time)
                : x + Math.max(3, scale * 500);

            const barWidth = Math.max(3, end - x);

            // Colored event marker
            CT.fillStyle = COLORS[e.j];

            CT.fillRect(
                x,
                y + 5,
                Math.min(6, barWidth),
                ROW - 10
            );

            // Gray elapsed interval
            if (barWidth > 9) {

                CT.fillStyle = '#49586b';

                CT.fillRect(
                    x + 6,
                    y + 10,
                    Math.max(0, barWidth - 7),
                    ROW - 20
                );
            }

            segments.push({
                x0: x,
                x1: Math.max(x + 6, end),
                y0: y,
                y1: y + ROW,
                d,
                stage: e.stage,
                time: e.time,
                nextTime: next ? next.time : null
            });
        });
    });

    // Divider between instruction names and timeline
    CT.strokeStyle = '#475569';

    CT.beginPath();
    CT.moveTo(LEFT - 6, 0);
    CT.lineTo(LEFT - 6, height);
    CT.stroke();

    drawAxes();
}


function fitTime() {

    const span = Math.max(
        1,
        maxTick - origin
    );

    scale = Math.min(
        2,
        Math.max(
            0.00001,
            (VP.clientWidth - LEFT - RIGHT) / span
        )
    );

    VP.scrollLeft = 0;
    draw();
}


// Zoom centered on the mouse position.
function zoom(factor, anchorX = VP.clientWidth / 2) {

    const oldScale = scale;

    const tickAtPointer =
        origin +
        (VP.scrollLeft + anchorX - LEFT) / oldScale;

    const newScale = Math.min(
        10,
        Math.max(0.00001, oldScale * factor)
    );

    if (newScale === oldScale) return;

    scale = newScale;

    draw();

    // Keep the same simulation time under the cursor.
    VP.scrollLeft = Math.max(
        0,
        tickToX(tickAtPointer) - anchorX
    );

    drawAxes();
}


// Determine instruction and stage under pointer.
function lookup(e) {

    const rect = CV.getBoundingClientRect();

    const x = e.clientX - rect.left;
    const y = e.clientY - rect.top;

    const i = Math.floor(y / ROW);

    if (i < 0 || i >= filtered.length) {
        return null;
    }

    const d = filtered[i];

    const stage = segments.find(s =>
        s.d === d &&
        x >= s.x0 &&
        x < s.x1
    );

    return {d, stage};
}


CV.addEventListener('mousemove', e => {

    const result = lookup(e);

    if (!result) {
        TIP.style.display = 'none';
        return;
    }

    const {d, stage} = result;

    const safe = d.instruction
        .replaceAll('&', '&amp;')
        .replaceAll('<', '&lt;')
        .replaceAll('>', '&gt;');

    let html =
        `<b>${safe}</b>` +
        `<br>Sequence: ${d.seq}` +
        `<br>PC: ${d.pc}`;

    if (stage) {

        const interval = stage.nextTime !== null
            ? stage.nextTime - stage.time
            : null;

        html +=
            `<br><b>Stage: ${stage.stage}</b>` +
            `<br>Tick: ${number(stage.time)}` +
            `<br>Cycle: ${number(stage.time / ticksPerCycle())}`;

        if (interval !== null) {

            html +=
                `<br>Next event: ${number(stage.nextTime)} ticks` +
                `<br>Interval: ${number(interval)} ticks` +
                `<br>Interval: ${number(interval / ticksPerCycle())} cycles`;
        }
    }

    TIP.innerHTML = html;
    TIP.style.display = 'block';

    TIP.style.left =
        Math.max(
            5,
            Math.min(e.clientX + 12, innerWidth - 350)
        ) + 'px';

    TIP.style.top =
        Math.max(
            5,
            Math.min(e.clientY + 12, innerHeight - 180)
        ) + 'px';
});


CV.addEventListener('mouseleave', () => {
    TIP.style.display = 'none';
});


CV.addEventListener('click', e => {

    const result = lookup(e);

    if (!result) return;

    const d = result.d;

    selected = d.seq;

    const tpc = ticksPerCycle();

    document.getElementById('details').textContent =
        `Instruction #${d.seq}: ${d.instruction}\n` +
        `PC: ${d.pc}\n\n` +
        `Stage        Ticks           CPU cycles\n` +
        `-------------------------------------------\n` +
        STAGES.map(s => {

            const t = d[s] || 0;

            return (
                s.padEnd(12) +
                (t ? number(t) : '—').padEnd(16) +
                (t ? number(t / tpc) : '—')
            );

        }).join('\n');

    draw();
});


// Search and filters
document.getElementById('search')
    .addEventListener('input', filterRecords);

document.getElementById('committed')
    .addEventListener('change', filterRecords);

document.getElementById('limit')
    .addEventListener('change', filterRecords);

document.getElementById('ticksPerCycle')
    .addEventListener('change', () => {
        drawAxes();
        selected = null;
        document.getElementById('details').textContent =
            'Click an instruction to inspect its pipeline timestamps.';
    });


// Zoom buttons
document.getElementById('zin').onclick =
    () => zoom(2);

document.getElementById('zout').onclick =
    () => zoom(0.5);

document.getElementById('fit').onclick =
    fitTime;


// Mouse wheel zoom
VP.addEventListener('wheel', e => {

    if (e.shiftKey) {

        e.preventDefault();

        VP.scrollLeft += e.deltaY;

        drawAxes();
        return;
    }

    e.preventDefault();

    const x =
        e.clientX - VP.getBoundingClientRect().left;

    const factor = Math.exp(
        -Math.max(-200, Math.min(200, e.deltaY)) * 0.002
    );

    zoom(factor, x);

}, {passive: false});


// Keep both axes synchronized while scrolling.
VP.addEventListener('scroll', drawAxes);

window.addEventListener('resize', () => {
    draw();
});


// Initialize viewer
filterRecords();

</script>
</body>
</html>
'''


def main():
    parser = argparse.ArgumentParser(
        description="gem5 O3PipeView HTML viewer"
    )

    parser.add_argument(
        "trace",
        help="Raw O3PipeView trace file"
    )

    parser.add_argument(
        "-o",
        "--output",
        default="o3_pipeline.html"
    )

    args = parser.parse_args()

    records = parse_trace(args.trace)

    if not records:
        parser.error(
            "No O3PipeView records found. "
            "Enable --debug-flags=O3PipeView."
        )

    html = HTML.replace(
        "__RECORDS__",
        json.dumps(records, separators=(",", ":"))
            .replace("</", "<\\/")
    )

    Path(args.output).write_text(
        html,
        encoding="utf-8"
    )

    print(
        f"Created {args.output} "
        f"with {len(records):,} instruction records"
    )


if __name__ == "__main__":
    main()
