/**
 * Fuzzy matching used by the command palette and the home-page grid.
 * Returns [score, matchedIndices[]]. Score 0 = no match.
 */
export function fuzzyMatch(query, target) {
    const q = query.toLowerCase();
    const t = target.toLowerCase();
    if (q.length === 0)
        return [1, []];
    const substringIdx = t.indexOf(q);
    if (substringIdx >= 0) {
        const indices = Array.from({ length: q.length }, (_, i) => substringIdx + i);
        return [100 + (q.length / t.length) * 50, indices];
    }
    let qi = 0;
    let score = 0;
    let consecutive = 0;
    let lastMatch = -1;
    const indices = [];
    for (let ti = 0; ti < t.length && qi < q.length; ti++) {
        if (t[ti] === q[qi]) {
            indices.push(ti);
            qi++;
            score += 1 + consecutive * 2;
            if (ti === 0 || t[ti - 1] === " " || t[ti - 1] === "-" || t[ti - 1] === "/") {
                score += 5;
            }
            if (lastMatch >= 0 && ti - lastMatch === 1) {
                consecutive++;
            }
            else {
                consecutive = 0;
            }
            lastMatch = ti;
        }
    }
    return qi === q.length ? [score, indices] : [0, []];
}
