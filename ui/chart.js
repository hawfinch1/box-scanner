export default function({parentElement, data}) {
    const root = parentElement.querySelector('.box-touch-chart');
    const plot = root.querySelector('.box-chart-plot');
    const status = root.querySelector('.box-chart-status');
    const Plotly = window.Plotly;
    root.querySelector('.box-chart-title').textContent = data.title;
    const legend = root.querySelector('.box-chart-legend');
    legend.replaceChildren();
    for (const item of data.legend) {
        const label = document.createElement('span');
        const swatch = document.createElement('i');
        swatch.style.backgroundColor = item.color;
        label.append(swatch, document.createTextNode(item.name));
        legend.append(label);
    }

    let disposed = false;
    let gesture = null;
    let touchSession = false;
    let frame = 0;
    let pending = null;
    let busy = false;
    let observer;
    const removers = [];
    const listen = (target, name, handler, options) => {
        target.addEventListener(name, handler, options);
        removers.push(() => target.removeEventListener(name, handler, options));
    };
    // Coalesce touch updates, including while a Plotly redraw is in progress.
    const flush = () => {
        frame = 0;
        if (disposed || busy || !pending) return;
        const update = pending;
        pending = null;
        busy = true;
        Promise.resolve(Plotly.relayout(plot, update)).finally(() => {
            busy = false;
            if (!disposed && pending) frame = requestAnimationFrame(flush);
        });
    };
    const queue = (update) => {
        pending = update;
        if (!frame && !busy) frame = requestAnimationFrame(flush);
    };
    const midpoint = (touches) => ({
        x: (touches[0].clientX + touches[1].clientX) / 2,
        y: (touches[0].clientY + touches[1].clientY) / 2,
        distance: Math.max(20, Math.hypot(touches[0].clientX - touches[1].clientX,
                                         touches[0].clientY - touches[1].clientY)),
    });
    // Date ranges need Plotly's conversions; numeric subtraction of date strings is invalid.
    const axisState = (axis) => ({
        axis,
        lo: axis.r2l(axis.range[0]),
        hi: axis.r2l(axis.range[1]),
    });
    const rangeUpdate = (x, y, factor, dx = 0, dy = 0, anchorX = 0.5, anchorY = 0.5) => {
        const change = (s, anchor, shift) => {
            const span = s.hi - s.lo;
            const lo = s.lo + span * anchor * (1 - factor) + shift * span;
            return [s.axis.l2r(lo), s.axis.l2r(lo + span * factor)];
        };
        const xr = change(x, anchorX, dx);
        return {
            'xaxis.range': xr, 'xaxis.autorange': false,
            'xaxis2.range': xr, 'xaxis2.autorange': false,
            'yaxis.range': change(y, anchorY, dy), 'yaxis.autorange': false,
        };
    };

    const ready = Plotly.newPlot(plot, data.figure.data, {
        ...data.figure.layout, height: undefined,
        paper_bgcolor: 'rgba(0,0,0,0)', plot_bgcolor: 'rgba(0,0,0,0)',
    }, {displayModeBar: false, scrollZoom: false, doubleClick: false, responsive: false});
    ready.then(() => {
        if (disposed) { Plotly.purge(plot); return; }
        observer = new ResizeObserver(() => Plotly.Plots.resize(plot));
        observer.observe(plot);
        for (const button of root.querySelectorAll('button')) {
            listen(button, 'click', () => {
                gesture = null;
                status.textContent = '';
                if (button.dataset.action === 'reset') {
                    queue({'xaxis.autorange': true, 'xaxis2.autorange': true,
                           'yaxis.autorange': true, 'yaxis2.autorange': true});
                } else {
                    queue(rangeUpdate(axisState(plot._fullLayout.xaxis),
                                      axisState(plot._fullLayout.yaxis),
                                      button.dataset.action === 'in' ? 0.8 : 1.25));
                }
            });
        }
        listen(plot, 'touchstart', (event) => {
            // Prevent Plotly's native single-finger drag without cancelling page scroll.
            event.stopImmediatePropagation();
            if (event.touches.length !== 2) return;
            event.preventDefault();
            touchSession = true;
            const point = midpoint(event.touches);
            const bounds = plot.getBoundingClientRect();
            const layout = plot._fullLayout;
            gesture = {
                ...point, xaxis: axisState(layout.xaxis), yaxis: axisState(layout.yaxis),
                width: layout.xaxis._length, height: layout.yaxis._length,
                anchorX: Math.max(0, Math.min(1, (point.x - bounds.left - layout.xaxis._offset) / layout.xaxis._length)),
                anchorY: Math.max(0, Math.min(1, 1 - (point.y - bounds.top - layout.yaxis._offset) / layout.yaxis._length)),
            };
            status.textContent = '차트 조작 중 · 두 손가락을 떼면 페이지 스크롤로 돌아감';
        }, {capture: true, passive: false});
        listen(plot, 'touchmove', (event) => {
            event.stopImmediatePropagation();
            if (touchSession) event.preventDefault();
            if (!gesture || event.touches.length !== 2) return;
            const point = midpoint(event.touches);
            const factor = Math.max(0.2, Math.min(5, gesture.distance / point.distance));
            queue(rangeUpdate(gesture.xaxis, gesture.yaxis, factor,
                -(point.x - gesture.x) / gesture.width * factor,
                (point.y - gesture.y) / gesture.height * factor,
                gesture.anchorX, gesture.anchorY));
        }, {capture: true, passive: false});
        const finish = (event) => {
            event.stopImmediatePropagation();
            if (touchSession) event.preventDefault();
            if (event.touches.length < 2) gesture = null;
            if (event.touches.length === 0) {
                touchSession = false;
                status.textContent = '';
            }
        };
        listen(plot, 'touchend', finish, {capture: true, passive: false});
        listen(plot, 'touchcancel', finish, {capture: true, passive: false});
    }).catch(() => { if (!disposed) status.textContent = '차트를 불러오지 못함. 새로고침 후 다시 확인해 주세요.'; });

    return () => {
        disposed = true;
        pending = null;
        cancelAnimationFrame(frame);
        observer?.disconnect();
        removers.forEach(remove => remove());
        if (plot._fullLayout && !busy) Plotly.purge(plot);
    };
}
