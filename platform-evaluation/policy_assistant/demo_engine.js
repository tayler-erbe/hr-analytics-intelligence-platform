/* JS port of text.py + retrieval.py (BM25 only) + answerer.py for the offline demo.
 * Pure functions, no DOM: the same file is inlined into index.html and required by node in
 * tests/test_demo_parity.py to check it reproduces the Python eval outcomes. */
(function (root) {
  "use strict";
  var K1 = 1.2, B = 0.75;

  function stem(t) {
    var n = t.length;
    if (n > 4 && t.endsWith("ies")) return t.slice(0, -3) + "y";
    if (n > 5 && t.endsWith("ing")) return t.slice(0, -3);
    if (n > 4 && t.endsWith("ed")) return t.slice(0, -2);
    if (n > 3 && t.endsWith("s") && !t.endsWith("ss") && !t.endsWith("us")) return t.slice(0, -1);
    return t;
  }

  function makeTokenizer(stopwords) {
    var stop = new Set(stopwords);
    return function tokenize(text) {
      text = text.toLowerCase().split("'").join("").split("’").join("");
      var m = text.match(/[a-z0-9]+/g) || [], out = [];
      for (var i = 0; i < m.length; i++) {
        if (stop.has(m[i])) continue;
        var s = stem(m[i]);
        if (!stop.has(s)) out.push(s);
      }
      return out;
    };
  }

  function sentences(text) {
    return text.split(/(?<=[.!?])\s+(?=[A-Z0-9"(])|\s+(?=- )/)
      .map(function (s) { return s.trim().replace(/^[ -]+|[ -]+$/g, ""); })
      .filter(function (s) { return s.length > 2; });
  }

  function indexText(c) {
    return [c.title || "", (c.heading_path || []).slice(1).join(" "), c.text].join(" ");
  }

  function Engine(data) {
    this.cfg = data.config;
    this.chunks = data.chunks;
    this.tokenize = makeTokenizer(data.config.stopwords);
    this.rules = data.config.policy_rules.map(function (r) { return { name: r[0], re: new RegExp(r[1], "i"), why: r[2] }; });
    var self = this;
    this.tokens = this.chunks.map(function (c) { return self.tokenize(indexText(c)); });
    this.sets = this.tokens.map(function (t) { return new Set(t); });
    this.N = this.chunks.length;
    this.df = new Map(); this.post = new Map(); this.tf = []; this.dl = [];
    var total = 0;
    for (var i = 0; i < this.N; i++) {
      var tf = new Map(), toks = this.tokens[i];
      for (var j = 0; j < toks.length; j++) tf.set(toks[j], (tf.get(toks[j]) || 0) + 1);
      this.tf.push(tf); this.dl.push(toks.length); total += toks.length;
      tf.forEach(function (_, term) {
        self.df.set(term, (self.df.get(term) || 0) + 1);
        if (!self.post.has(term)) self.post.set(term, []);
        self.post.get(term).push(i);
      });
    }
    this.avgdl = this.N ? total / this.N : 0;
  }

  Engine.prototype.idf = function (t) {
    var n = this.df.get(t) || 0;
    return Math.log(1 + (this.N - n + 0.5) / (n + 0.5));
  };

  Engine.prototype.search = function (query, k, perPage) {
    k = k || this.cfg.top_k; perPage = perPage || 2;
    var q = Array.from(new Set(this.tokenize(query))), scores = new Map(), self = this;
    // iterate terms in first-occurrence order (Python iterates a set; float sums are
    // order-sensitive only in the last ulp, ranking ties are broken by chunk index)
    q.forEach(function (term) {
      var idf = self.idf(term), p = self.post.get(term) || [];
      for (var x = 0; x < p.length; x++) {
        var i = p[x], f = self.tf[i].get(term);
        var s = idf * f * (K1 + 1) / (f + K1 * (1 - B + B * self.dl[i] / self.avgdl));
        scores.set(i, (scores.get(i) || 0) + s);
      }
    });
    var order = Array.from(scores.keys()).sort(function (a, b) { return (scores.get(b) - scores.get(a)) || (a - b); });
    var hits = [], per = new Map();
    for (var r = 0; r < order.length && hits.length < k; r++) {
      var i = order[r], url = this.chunks[i].url;
      if ((per.get(url) || 0) >= perPage) continue;
      per.set(url, (per.get(url) || 0) + 1);
      hits.push({ i: i, chunk: this.chunks[i], bm25: scores.get(i) });
    }
    return hits;
  };

  Engine.prototype.coverage = function (query, i) {
    var q = Array.from(new Set(this.tokenize(query))), tot = 0, got = 0, self = this;
    if (!q.length) return 0;
    q.forEach(function (t) { var w = self.idf(t); tot += w; if (self.sets[i].has(t)) got += w; });
    return tot ? got / tot : 0;
  };

  Engine.prototype.policy = function (question) {
    var q = " " + question.split("’").join("'").replace(/\s+/g, " ") + " ";
    for (var r = 0; r < this.rules.length; r++) if (this.rules[r].re.test(q)) return this.rules[r];
    return null;
  };

  Engine.prototype.bestSentences = function (question, texts, n) {
    var q = new Set(this.tokenize(question)), scored = [], self = this;
    texts.forEach(function (text, ci) {
      sentences(text).forEach(function (s, si) {
        if (s.split(/\s+/).filter(Boolean).length < 6) return;
        var sc = 0;
        new Set(self.tokenize(s)).forEach(function (t) { if (q.has(t)) sc += self.idf(t); });
        sc = sc * (1 - 0.15 * ci);
        if (sc > 0) scored.push({ sc: sc, ci: ci, si: si, s: s });
      });
    });
    scored.sort(function (a, b) { return (b.sc - a.sc) || (a.ci - b.ci) || (a.si - b.si); });
    var out = [], seen = new Set();
    for (var x = 0; x < scored.length && out.length < n; x++) {
      if (seen.has(scored[x].s)) continue;
      seen.add(scored[x].s); out.push(scored[x]);
    }
    return out;
  };

  Engine.prototype.answer = function (question) {
    var cfg = this.cfg, self = this;
    if (!this.tokenize(question).length) return { status: "abstain", reason: "empty_query", citations: [], related: [] };
    var pol = this.policy(question);
    if (pol) return { status: "abstain", reason: pol.name, why: pol.why, citations: [], related: [] };
    var hits = this.search(question, cfg.top_k);
    var cites = hits.map(function (h, n) {
      return { n: n + 1, chunk: h.chunk, url: h.chunk.url, bm25: h.bm25, coverage: self.coverage(question, h.i) };
    });
    var bestCov = 0, bestBm = 0;
    cites.slice(0, 3).forEach(function (c) { bestCov = Math.max(bestCov, c.coverage); });
    cites.forEach(function (c) { bestBm = Math.max(bestBm, c.bm25); });
    // Python rounds before comparing; mirror that so the gate matches exactly
    bestCov = Math.round(bestCov * 1000) / 1000; bestBm = Math.round(bestBm * 1000) / 1000;
    var trace = { top_bm25: bestBm, top_coverage: bestCov };
    if (!cites.length || bestCov < cfg.min_coverage || bestBm < cfg.min_score) {
      return { status: "abstain", reason: "weak_evidence", citations: [], trace: trace,
        related: cites.slice(0, 3).map(function (c) { return { title: c.chunk.title, url: c.url }; }) };
    }
    var support = cites.filter(function (c) {
      return Math.round(c.coverage * 1000) / 1000 >= cfg.min_coverage * 0.67 && c.bm25 > 0;
    });
    if (!support.length) support = [cites[0]];
    support.forEach(function (c, n) { c.n = n + 1; });
    var picked = this.bestSentences(question, support.slice(0, 3).map(function (c) { return c.chunk.text; }), 2);
    return { status: "answer", reason: "supported", citations: support, picked: picked, trace: trace, related: [] };
  };

  var api = { Engine: Engine, stem: stem, makeTokenizer: makeTokenizer, sentences: sentences };
  if (typeof module !== "undefined" && module.exports) module.exports = api;
  else root.PolicyEngine = api;
})(this);
