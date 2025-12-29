const DATA_PATHS = ["data/property_listings.json", "../data/property_listings.json"];

const elements = {
  totalCount: document.getElementById("totalCount"),
  filteredCount: document.getElementById("filteredCount"),
  cards: document.getElementById("cards"),
  emptyState: document.getElementById("emptyState"),
  activeChips: document.getElementById("activeChips"),
  lastFetch: document.getElementById("lastFetch"),
  refreshBtn: document.getElementById("refreshBtn"),
  clearBtn: document.getElementById("clearBtn"),
  sourceFilter: document.getElementById("sourceFilter"),
  stateFilter: document.getElementById("stateFilter"),
  cityFilter: document.getElementById("cityFilter"),
  bankFilter: document.getElementById("bankFilter"),
  typeFilter: document.getElementById("typeFilter"),
  minPrice: document.getElementById("minPrice"),
  maxPrice: document.getElementById("maxPrice"),
  searchInput: document.getElementById("searchInput"),
  photoOnly: document.getElementById("photoOnly"),
};

let listings = [];

const formatter = new Intl.NumberFormat("en-IN", {
  style: "currency",
  currency: "INR",
  maximumFractionDigits: 0,
});

const safeText = (value) => (value === null || value === undefined ? "" : String(value));

const parsePrice = (value) => {
  if (value === null || value === undefined) return null;
  if (typeof value === "number") return Number.isFinite(value) ? value : null;
  const cleaned = safeText(value).replace(/[^0-9.]/g, "");
  if (!cleaned) return null;
  const parsed = Number.parseFloat(cleaned);
  return Number.isFinite(parsed) ? parsed : null;
};

const formatPrice = (value, rawValue) => {
  if (value !== null) return formatter.format(value);
  if (rawValue) return safeText(rawValue);
  return "Not listed";
};

const resolveImage = (item, raw) => {
  const candidates = [item.photos, item.link, raw.photos, raw.photo];
  const isImage = (url) =>
    /\.(jpg|jpeg|png|webp)$/i.test(url) || url.includes("cloudfront");
  for (const candidate of candidates) {
    if (!candidate) continue;
    const url = safeText(candidate);
    if (url.startsWith("http") && isImage(url)) return url;
    if (!url.startsWith("http") && isImage(url)) {
      return `https://d14q55p4nerl4m.cloudfront.net/${url}`;
    }
  }
  return "";
};

const getAuctionDate = (item, raw) => {
  if (raw.auction_date) return raw.auction_date;
  if (item.important_dates) {
    const dateEntry = item.important_dates.find((date) =>
      safeText(date.key).toLowerCase().includes("auction")
    );
    if (dateEntry) return dateEntry.value;
  }
  return "";
};

const normalizeListing = (item, index) => {
  const raw = item.raw || {};
  const priceValue = parsePrice(raw.price ?? item.price);
  const link = item.link || raw.property_url || "";
  return {
    id: raw.propertyId || raw.bankPropertyId || link || `listing-${index}`,
    source: item.source || raw.source || "unknown",
    title:
      raw.projectName ||
      raw.propertySubType ||
      raw.typeOfAsset ||
      item.details ||
      "Property",
    city: raw.city || item.city || raw.districtname || "",
    state: raw.statename || "",
    bank: raw.bankName || "",
    type: item.property_type || raw.propertySubType || raw.typeOfAsset || "",
    priceValue,
    priceLabel: formatPrice(priceValue, raw.price),
    postedOn: raw.postedOn || "",
    auctionDate: getAuctionDate(item, raw),
    address: raw.address || raw.localities || "",
    details: item.details || raw.summaryDesc || "",
    link,
    image: resolveImage(item, raw),
  };
};

const dedupeListings = (items) => {
  const seen = new Set();
  const output = [];
  for (const item of items) {
    const key = [
      safeText(item.link).toLowerCase(),
      safeText(item.title).toLowerCase(),
      safeText(item.priceLabel).toLowerCase(),
      safeText(item.city).toLowerCase(),
      safeText(item.source).toLowerCase(),
    ].join("|");
    if (seen.has(key)) continue;
    seen.add(key);
    output.push(item);
  }
  return output;
};

const dedupe = (values) =>
  [...new Set(values.filter((value) => value && String(value).trim()))].sort(
    (a, b) => safeText(a).localeCompare(safeText(b))
  );

const fillSelect = (select, options) => {
  select.innerHTML = "";
  const blank = document.createElement("option");
  blank.value = "";
  blank.textContent = "All";
  select.appendChild(blank);
  options.forEach((option) => {
    const item = document.createElement("option");
    item.value = option;
    item.textContent = option;
    select.appendChild(item);
  });
};

const buildFilters = () => {
  fillSelect(elements.sourceFilter, dedupe(listings.map((item) => item.source)));
  fillSelect(elements.stateFilter, dedupe(listings.map((item) => item.state)));
  fillSelect(elements.cityFilter, dedupe(listings.map((item) => item.city)));
  fillSelect(elements.bankFilter, dedupe(listings.map((item) => item.bank)));
  fillSelect(elements.typeFilter, dedupe(listings.map((item) => item.type)));
};

const getFilterState = () => ({
  source: elements.sourceFilter.value,
  state: elements.stateFilter.value,
  city: elements.cityFilter.value,
  bank: elements.bankFilter.value,
  type: elements.typeFilter.value,
  minPrice: parsePrice(elements.minPrice.value),
  maxPrice: parsePrice(elements.maxPrice.value),
  search: elements.searchInput.value.trim().toLowerCase(),
  photos: elements.photoOnly.checked,
});

const applyFilters = () => {
  const filters = getFilterState();
  const filtered = listings.filter((item) => {
    if (filters.source && item.source !== filters.source) return false;
    if (filters.state && item.state !== filters.state) return false;
    if (filters.city && item.city !== filters.city) return false;
    if (filters.bank && item.bank !== filters.bank) return false;
    if (filters.type && item.type !== filters.type) return false;
    if (filters.photos && !item.image) return false;
    if (filters.minPrice !== null) {
      if (item.priceValue === null || item.priceValue < filters.minPrice) return false;
    }
    if (filters.maxPrice !== null) {
      if (item.priceValue === null || item.priceValue > filters.maxPrice) return false;
    }
    if (filters.search) {
      const haystack = [
        item.title,
        item.details,
        item.address,
        item.bank,
        item.city,
        item.state,
      ]
        .map((value) => safeText(value).toLowerCase())
        .join(" ");
      if (!haystack.includes(filters.search)) return false;
    }
    return true;
  });
  renderListings(filtered);
  renderChips(filters);
};

const renderChips = (filters) => {
  elements.activeChips.innerHTML = "";
  const entries = [
    filters.source && `Source: ${filters.source}`,
    filters.state && `State: ${filters.state}`,
    filters.city && `City: ${filters.city}`,
    filters.bank && `Bank: ${filters.bank}`,
    filters.type && `Type: ${filters.type}`,
    filters.minPrice !== null && `Min INR ${filters.minPrice}`,
    filters.maxPrice !== null && `Max INR ${filters.maxPrice}`,
    filters.photos && "Has photos",
    filters.search && `Search: ${filters.search}`,
  ].filter(Boolean);
  entries.forEach((entry) => {
    const chip = document.createElement("span");
    chip.className = "chip";
    chip.textContent = entry;
    elements.activeChips.appendChild(chip);
  });
};

const renderListings = (items) => {
  elements.cards.innerHTML = "";
  elements.filteredCount.textContent = String(items.length);
  if (!items.length) {
    elements.emptyState.classList.remove("hidden");
    return;
  }
  elements.emptyState.classList.add("hidden");
  items.forEach((item) => {
    const card = document.createElement("article");
    card.className = "card";

    const imageWrap = document.createElement("div");
    imageWrap.className = "card-image";
    if (item.image) {
      const img = document.createElement("img");
      img.loading = "lazy";
      img.src = item.image;
      img.alt = item.title;
      imageWrap.appendChild(img);
    }

    const body = document.createElement("div");
    body.className = "card-body";

    const title = document.createElement("h3");
    title.className = "card-title";
    title.textContent = item.title;

    const meta = document.createElement("div");
    meta.className = "card-meta";

    const location = document.createElement("div");
    location.textContent = [item.city, item.state].filter(Boolean).join(", ");

    const bank = document.createElement("div");
    bank.textContent = item.bank ? `Bank: ${item.bank}` : "Bank: -";

    const price = document.createElement("div");
    const pricePill = document.createElement("span");
    pricePill.className = "pill";
    pricePill.textContent = item.priceLabel;
    price.appendChild(pricePill);

    const dates = document.createElement("div");
    const dateParts = [item.auctionDate && `Auction: ${item.auctionDate}`, item.postedOn];
    dates.textContent = dateParts.filter(Boolean).join(" • ");

    const source = document.createElement("div");
    source.textContent = `Source: ${item.source}`;

    meta.append(location, bank, price, dates, source);

    const details = document.createElement("p");
    details.className = "card-details";
    details.textContent = item.details || item.address || "No description available.";

    body.append(title, meta, details);

    if (item.link && item.link !== item.image) {
      const link = document.createElement("a");
      link.className = "card-link";
      link.href = item.link;
      link.target = "_blank";
      link.rel = "noopener noreferrer";
      link.textContent = "View listing";
      body.appendChild(link);
    }

    card.append(imageWrap, body);
    elements.cards.appendChild(card);
  });
};

const clearFilters = () => {
  elements.sourceFilter.value = "";
  elements.stateFilter.value = "";
  elements.cityFilter.value = "";
  elements.bankFilter.value = "";
  elements.typeFilter.value = "";
  elements.minPrice.value = "";
  elements.maxPrice.value = "";
  elements.searchInput.value = "";
  elements.photoOnly.checked = false;
  applyFilters();
};

const fetchJson = async () => {
  let lastError;
  for (const path of DATA_PATHS) {
    try {
      const response = await fetch(`${path}?t=${Date.now()}`);
      if (!response.ok) throw new Error(`HTTP ${response.status}`);
      return await response.json();
    } catch (error) {
      lastError = error;
    }
  }
  throw lastError || new Error("Unable to load data.");
};

const updateTimestamp = () => {
  const now = new Date();
  elements.lastFetch.textContent = now.toLocaleString();
};

const loadData = async () => {
  elements.refreshBtn.disabled = true;
  elements.refreshBtn.textContent = "Refreshing...";
  try {
    const data = await fetchJson();
    listings = dedupeListings((Array.isArray(data) ? data : []).map(normalizeListing));
    elements.totalCount.textContent = String(listings.length);
    buildFilters();
    applyFilters();
    updateTimestamp();
  } catch (error) {
    elements.cards.innerHTML = "";
    elements.emptyState.classList.remove("hidden");
    elements.emptyState.textContent =
      "Unable to load data. Check that property_listings.json is available.";
  } finally {
    elements.refreshBtn.disabled = false;
    elements.refreshBtn.textContent = "Refresh data";
  }
};

[
  elements.sourceFilter,
  elements.stateFilter,
  elements.cityFilter,
  elements.bankFilter,
  elements.typeFilter,
  elements.minPrice,
  elements.maxPrice,
  elements.searchInput,
  elements.photoOnly,
].forEach((input) => {
  input.addEventListener("input", applyFilters);
  input.addEventListener("change", applyFilters);
});

elements.refreshBtn.addEventListener("click", loadData);
elements.clearBtn.addEventListener("click", clearFilters);

loadData();
