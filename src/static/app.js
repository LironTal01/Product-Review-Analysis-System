// PRAS — frontend logic. Vanilla JS, no framework.
// Talks to POST /api/analyze and renders the AnalysisResult JSON into the DOM.

(function () {
  "use strict";

  // ---- DOM refs ----
  const form = document.getElementById("analyze-form");
  const urlInput = document.getElementById("amazon-url");
  const urlError = document.getElementById("url-error");
  const maxReviewsInput = document.getElementById("max-reviews");
  const maxReviewsValue = document.getElementById("max-reviews-value");
  const analyzeBtn = document.getElementById("analyze-btn");

  const loadingEl = document.getElementById("loading");
  const errorEl = document.getElementById("error");
  const resultsEl = document.getElementById("results");

  const examplesSection = document.getElementById("examples");
  const examplesList = document.getElementById("examples-list");
  const recentSidebar = document.getElementById("recent-sidebar");
  const recentSection = document.getElementById("recent-section");
  const recentList = document.getElementById("recent-list");
  const recentClearBtn = document.getElementById("recent-clear");

  // Result targets
  const productImage = document.getElementById("product-image");
  const productTitle = document.getElementById("product-title");
  const productPrice = document.getElementById("product-price");
  const amazonRating = document.getElementById("amazon-rating");
  const totalReviewCount = document.getElementById("total-review-count");
  const analyzedChip = document.getElementById("analyzed-chip");
  const requestedChip = document.getElementById("requested-chip");
  const accessNote = document.getElementById("access-note");
  const summaryText = document.getElementById("summary-text");
  const recommendation = document.getElementById("recommendation");
  const confidenceFill = document.getElementById("confidence-fill");
  const confidenceScore = document.getElementById("confidence-score");
  const confidenceBasis = document.getElementById("confidence-basis");
  const confidenceExplanation = document.getElementById("confidence-explanation");
  const prosList = document.getElementById("pros-list");
  const consList = document.getElementById("cons-list");
  const negativeSummary = document.getElementById("negative-summary");

  // ---- Constants ----
  const RECENT_KEY = "pras.recentSearches.v1";
  const RECENT_MAX = 5;

  // Mirrors the server-side AMAZON_DOMAINS list in src/utils/url_parser.py.
  const AMAZON_HOST_RE = /^(?:[a-z0-9-]+\.)?amazon\.(?:com|co\.uk|de|fr|ca|com\.au|it|es|co\.jp|in)$/i;
  const SMILE_HOST = "smile.amazon.com";

  const EXAMPLE_URLS = [
    {
      label: "Echo Dot",
      url: "https://www.amazon.com/dp/B08N5WRWNW",
    },
    {
      label: "Sample headphones",
      url: "https://www.amazon.com/dp/B0DGW54P27",
    },
    {
      label: "Kindle Paperwhite",
      url: "https://www.amazon.com/dp/B08KTZ8249",
    },
  ];


  // ---- Init ----
  renderExamples();
  renderRecent();

  maxReviewsInput.addEventListener("input", () => {
    maxReviewsValue.textContent = maxReviewsInput.value;
  });

  urlInput.addEventListener("input", () => {
    if (urlInput.classList.contains("invalid")) {
      // Clear validation styling as the user keeps typing.
      clearUrlError();
    }
  });

  urlInput.addEventListener("blur", () => {
    const value = urlInput.value.trim();
    if (!value) {
      clearUrlError();
      return;
    }
    const reason = validateAmazonUrlClient(value);
    if (reason) {
      showUrlError(reason);
    } else {
      clearUrlError();
    }
  });

  recentClearBtn.addEventListener("click", () => {
    saveRecent([]);
    renderRecent();
  });

  form.addEventListener("submit", async (event) => {
    event.preventDefault();
    const value = urlInput.value.trim();
    const reason = validateAmazonUrlClient(value);
    if (reason) {
      showUrlError(reason);
      urlInput.focus();
      return;
    }
    clearUrlError();
    await runAnalyze(value, Number(maxReviewsInput.value));
  });

  // ---- Core flow ----
  async function runAnalyze(amazonUrl, maxReviews) {
    setLoading(true);
    hideError();
    resultsEl.classList.add("hidden");

    try {
      const response = await fetch("/api/analyze", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ amazon_url: amazonUrl, max_reviews: maxReviews }),
      });

      const data = await response.json().catch(() => null);

      if (!response.ok) {
        const detail =
          (data && (data.detail || data.error)) ||
          `Request failed with status ${response.status}`;
        showError(typeof detail === "string" ? detail : JSON.stringify(detail));
        return;
      }

      if (!data) {
        showError("Empty response from server.");
        return;
      }

      renderResult(data, maxReviews);
      pushRecent(amazonUrl, data.product_title || "Product");
      renderRecent();
      resultsEl.classList.remove("hidden");
      examplesSection.classList.add("hidden");
      requestAnimationFrame(() => {
        const card = document.querySelector(".product-header");
        if (card) {
          const y = card.getBoundingClientRect().top + window.scrollY - 30;
          window.scrollTo({ top: y, behavior: "smooth" });
        }
      });
    } catch (err) {
      showError("Network error: " + (err && err.message ? err.message : String(err)));
    } finally {
      setLoading(false);
    }
  }

  function setLoading(isLoading) {
    if (isLoading) {
      loadingEl.classList.remove("hidden");
      examplesSection.classList.add("hidden");
      analyzeBtn.disabled = true;
      analyzeBtn.textContent = "Analyzing…";
    } else {
      loadingEl.classList.add("hidden");
      analyzeBtn.disabled = false;
      analyzeBtn.textContent = "Analyze reviews";
      if (resultsEl.classList.contains("hidden")) {
        examplesSection.classList.remove("hidden");
      }
    }
  }

  function showError(message) {
    errorEl.textContent = message;
    errorEl.classList.remove("hidden");
  }

  function hideError() {
    errorEl.textContent = "";
    errorEl.classList.add("hidden");
  }

  function showUrlError(message) {
    urlError.textContent = message;
    urlError.classList.remove("hidden");
    urlInput.classList.add("invalid");
    urlInput.setAttribute("aria-invalid", "true");
  }

  function clearUrlError() {
    urlError.textContent = "";
    urlError.classList.add("hidden");
    urlInput.classList.remove("invalid");
    urlInput.removeAttribute("aria-invalid");
  }

  // ---- Validation ----
  function validateAmazonUrlClient(value) {
    if (!value) return "Please enter a URL.";

    let parsed;
    try {
      parsed = new URL(value);
    } catch {
      return "That doesn't look like a valid URL.";
    }

    if (parsed.protocol !== "http:" && parsed.protocol !== "https:") {
      return "Only http and https URLs are supported.";
    }

    const host = parsed.hostname.toLowerCase().replace(/^www\./, "");
    if (!AMAZON_HOST_RE.test(host) && host !== SMILE_HOST) {
      return "Use a link from amazon.com (or another Amazon domain).";
    }

    if (!/\/(dp|gp\/product)\/[A-Z0-9]{8,12}/i.test(parsed.pathname)) {
      return "URL must contain a product id (e.g. /dp/B0...).";
    }

    return "";
  }

  // ---- Rendering ----
  function renderResult(data, requestedMaxReviews) {
    productTitle.textContent = data.product_title || "Product";

    if (data.product_image_url) {
      productImage.src = data.product_image_url;
      productImage.alt = data.product_title || "Product image";
    } else {
      productImage.removeAttribute("src");
      productImage.alt = "";
    }

    productPrice.textContent = data.product_price || "";

    const rating = Number(data.amazon_rating);
    amazonRating.textContent = rating > 0 ? `★ ${rating.toFixed(1)}  Amazon average rating` : "";
    amazonRating.classList.toggle("hidden", !(rating > 0));

    const reviewCount = Number(data.total_review_count);
    const analyzedCount = Number(data.total_reviews_analyzed || 0);
    totalReviewCount.textContent = reviewCount > 0 ? `${reviewCount.toLocaleString()} total reviews` : "";
    totalReviewCount.classList.toggle("hidden", !(reviewCount > 0));

    const requested = Number(requestedMaxReviews || 0);
    if (requested > 0) {
      analyzedChip.textContent =
        analyzedCount > 0
          ? `Analyzed ${analyzedCount.toLocaleString()} unique reviews (requested up to ${requested.toLocaleString()}).`
          : `Analyzed 0 reviews (requested up to ${requested.toLocaleString()}).`;
    } else {
      analyzedChip.textContent =
        analyzedCount > 0 ? `Analyzed ${analyzedCount.toLocaleString()} unique reviews.` : "Analyzed 0 reviews.";
    }
    requestedChip.textContent = "";
    requestedChip.classList.add("hidden");
    accessNote.textContent = "";
    accessNote.classList.add("hidden");

    summaryText.textContent = data.summary_text || "—";
    const rec = normalizeRecommendation(data.recommendation || "—");
    recommendation.textContent = rec.text;
    recommendation.classList.remove("rec-buy", "rec-dont-buy", "rec-neutral");
    recommendation.classList.add(rec.kind === "buy" ? "rec-buy" : rec.kind === "dont-buy" ? "rec-dont-buy" : "rec-neutral");

    const confidence = clamp01(Number(data.confidence_score) || 0);
    const confidencePct = Math.round(confidence * 100);
    const circumference = 2 * Math.PI * 42;
    confidenceFill.style.strokeDasharray = circumference;
    confidenceFill.style.strokeDashoffset = circumference * (1 - confidence);
    confidenceFill.classList.remove("low", "medium", "high");
    if (confidencePct < 40) confidenceFill.classList.add("low");
    else if (confidencePct < 70) confidenceFill.classList.add("medium");
    else confidenceFill.classList.add("high");
    confidenceScore.textContent = confidencePct + "%";

    if (analyzedCount > 0) {
      confidenceBasis.textContent = `Based on ${analyzedCount.toLocaleString()} unique reviews retrieved for this request.`;
      confidenceBasis.classList.remove("hidden");
    } else {
      confidenceBasis.textContent = "";
      confidenceBasis.classList.add("hidden");
    }
    confidenceExplanation.textContent = data.confidence_explanation || "";

    renderList(prosList, data.pros, "No pros highlighted yet.");
    renderList(consList, data.cons, "No cons highlighted yet.");

    negativeSummary.textContent =
      data.negative_summary || "No notable complaints found.";

  }

  function normalizeRecommendation(value) {
    const raw = String(value || "").trim();
    if (!raw || raw === "—") return { text: "—", kind: "neutral" };

    const norm = raw
      .toLowerCase()
      .replace(/[^\w\s']/g, " ")
      .replace(/\s+/g, " ")
      .trim();

    const isDontBuy =
      /don'?t\s*buy|do\s*not\s*buy|not\s*recommend|avoid|skip|stay\s*away|pass\b/.test(norm) ||
      (/\b(not|don'?t|avoid|below|alternative|skip)\b/.test(norm) &&
        /\b(buy|recommend|purchase)\b/.test(norm));

    if (isDontBuy) return { text: "Don't buy", kind: "dont-buy" };

    const isBuy =
      /\b(buy|purchase|recommend|worth|consider\s*buying|go\s*for|great|solid\s*choice)\b/.test(norm) &&
      !/don'?t|not|avoid|alternative|skip/.test(norm);

    if (isBuy) return { text: "Buy", kind: "buy" };

    if (/consider|mixed|depends|conditional|caveats|aware|willing/.test(norm))
      return { text: "Buy", kind: "buy" };

    return { text: toSentenceCase(raw), kind: "neutral" };
  }

  function toSentenceCase(text) {
    const s = String(text || "").trim();
    if (!s) return s;
    return s.replace(/(^\w|[.!?]\s+\w)/g, (ch) => ch.toUpperCase());
  }

  function renderList(ul, items, emptyMessage) {
    ul.innerHTML = "";
    if (!Array.isArray(items) || items.length === 0) {
      const li = document.createElement("li");
      li.className = "empty-state";
      li.textContent = emptyMessage;
      ul.appendChild(li);
      return;
    }
    for (const item of items) {
      const li = document.createElement("li");
      li.textContent = String(item);
      ul.appendChild(li);
    }
  }

  // ---- Examples + recent ----
  function renderExamples() {
    examplesList.innerHTML = "";
    for (const example of EXAMPLE_URLS) {
      const li = document.createElement("li");
      const btn = document.createElement("button");
      btn.type = "button";
      btn.className = "url-chip";
      btn.title = example.url;

      const labelSpan = document.createElement("span");
      labelSpan.className = "chip-label";
      labelSpan.textContent = example.label;
      btn.appendChild(labelSpan);

      btn.addEventListener("click", () => {
        urlInput.value = example.url;
        clearUrlError();
        urlInput.focus();
      });

      li.appendChild(btn);
      examplesList.appendChild(li);
    }
  }

  function loadRecent() {
    try {
      const raw = localStorage.getItem(RECENT_KEY);
      if (!raw) return [];
      const parsed = JSON.parse(raw);
      if (!Array.isArray(parsed)) return [];
      return parsed
        .filter((entry) => entry && typeof entry.url === "string")
        .slice(0, RECENT_MAX);
    } catch {
      return [];
    }
  }

  function saveRecent(entries) {
    try {
      localStorage.setItem(RECENT_KEY, JSON.stringify(entries));
    } catch {
      // localStorage is best-effort; ignore quota / privacy errors.
    }
  }

  function pushRecent(url, label) {
    const entries = loadRecent().filter((entry) => entry.url !== url);
    entries.unshift({
      url,
      label: label || url,
      ts: Date.now(),
    });
    saveRecent(entries.slice(0, RECENT_MAX));
  }

  function renderRecent() {
    const entries = loadRecent();
    recentList.innerHTML = "";

    if (entries.length === 0) {
      recentSection.classList.add("hidden");
      if (recentSidebar) recentSidebar.classList.add("hidden");
      return;
    }

    if (recentSidebar) recentSidebar.classList.remove("hidden");
    recentSection.classList.remove("hidden");

    for (const entry of entries) {
      const li = document.createElement("li");
      const btn = document.createElement("button");
      btn.type = "button";
      btn.className = "url-chip";
      btn.title = entry.url;

      const labelSpan = document.createElement("span");
      labelSpan.className = "chip-label";
      labelSpan.textContent = entry.label || entry.url;
      btn.appendChild(labelSpan);

      btn.addEventListener("click", () => {
        urlInput.value = entry.url;
        clearUrlError();
        urlInput.focus();
      });

      li.appendChild(btn);
      recentList.appendChild(li);
    }
  }

  function clamp01(value) {
    if (Number.isNaN(value)) return 0;
    if (value < 0) return 0;
    if (value > 1) return 1;
    return value;
  }
})();
