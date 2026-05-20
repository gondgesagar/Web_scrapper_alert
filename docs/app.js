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
  emptyClearBtn: document.getElementById("emptyClearBtn"),
  filtersToggle: document.getElementById("filtersToggle"),
  sidebar: document.getElementById("sidebar"),
  sourceFilter: document.getElementById("sourceFilter"),
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

const INVALID_URL_RE =
  /javascript:|void\s*\(\s*0|vdo\.ai|ezoic|doubleclick|googlesyndication|\/contact(?:-us)?(?:\/|$|\?)|blog-details|\/city\/[^/]+\/?$/i;

const isValidListingUrl = (url, source = "") => {
  const value = safeText(url).trim();
  if (!value.startsWith("http://") && !value.startsWith("https://")) return false;
  if (INVALID_URL_RE.test(value)) return false;
  const lower = value.toLowerCase();
  if (lower.includes("cloudfront.net") && /\.(jpg|jpeg|png|webp|gif)(\?|$)/i.test(lower)) {
    return false;
  }
  const src = safeText(source).toLowerCase();
  const patterns = {
    eauctionsindia: /eauctionsindia\.com\/properties\/\d+/i,
    baanknet: /baanknet\.com\/view-property\/\d+/i,
    bankauctions: /bankauctions\.in\/auction\//i,
    findauction: /findauction\.in\/auction\//i,
    mhada: /eauction\.mhada\.gov\.in\//i,
    mstc: /mstcecommerce\.com\/auctionhome\//i,
  };
  const pattern = patterns[src];
  if (pattern) return pattern.test(lower);
  return true;
};

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
  fillSelect(elements.cityFilter, dedupe(listings.map((item) => item.city)));
  fillSelect(elements.bankFilter, dedupe(listings.map((item) => item.bank)));
  fillSelect(elements.typeFilter, dedupe(listings.map((item) => item.type)));
};

const getFilterState = () => ({
  source: elements.sourceFilter.value,
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
    filters.search && `"${filters.search}"`,
    filters.city && filters.city,
    filters.source && formatSource(filters.source),
    filters.type && filters.type,
    filters.bank && filters.bank,
    filters.minPrice !== null && `Min ${formatter.format(filters.minPrice)}`,
    filters.maxPrice !== null && `Max ${formatter.format(filters.maxPrice)}`,
    filters.photos && "With photos",
  ].filter(Boolean);
  entries.forEach((entry) => {
    const chip = document.createElement("span");
    chip.className = "chip";
    chip.textContent = entry;
    elements.activeChips.appendChild(chip);
  });
};

const formatSource = (source) => {
  const labels = {
    eauctionsindia: "eAuctions India",
    baanknet: "BAANKNET",
    bankauctions: "BankAuctions.in",
    findauction: "FindAuction.in",
    mhada: "MHADA eAuction",
    mstc: "MSTC / IBAPI",
  };
  const s = safeText(source).toLowerCase();
  return labels[s] || source || "Unknown";
};

const renderListings = (items) => {
  elements.cards.innerHTML = "";
  elements.filteredCount.textContent = String(items.length);
  if (!items.length) {
    elements.emptyState.classList.remove("hidden");
    elements.cards.classList.add("hidden");
    return;
  }
  elements.emptyState.classList.add("hidden");
  elements.cards.classList.remove("hidden");

  items.forEach((item) => {
    const card = document.createElement("article");
    card.className = item.image ? "card" : "card card--no-photo";

    const body = document.createElement("div");
    body.className = "card-body";

    const badges = document.createElement("div");
    badges.className = "card-badges";
    const sourceBadge = document.createElement("span");
    sourceBadge.className = "badge badge--source";
    sourceBadge.textContent = formatSource(item.source);
    badges.appendChild(sourceBadge);
    if (item.type) {
      const typeBadge = document.createElement("span");
      typeBadge.className = "badge badge--type";
      typeBadge.textContent = item.type;
      badges.appendChild(typeBadge);
    }

    const title = document.createElement("h3");
    title.className = "card-title";
    title.textContent = item.title;

    const location = document.createElement("div");
    location.className = "card-location";
    const locText = [item.city, item.state || "Maharashtra"].filter(Boolean).join(", ");
    location.textContent = locText || "Maharashtra";

    const price = document.createElement("div");
    price.className = "card-price";
    price.textContent = item.priceLabel;

    const metaRow = document.createElement("div");
    metaRow.className = "card-meta-row";
    if (item.bank) {
      const bank = document.createElement("span");
      bank.className = "card-meta-item";
      bank.innerHTML = `<strong>Bank</strong> ${item.bank}`;
      metaRow.appendChild(bank);
    }
    if (item.auctionDate) {
      const auction = document.createElement("span");
      auction.className = "card-meta-item";
      auction.innerHTML = `<strong>Auction</strong> ${item.auctionDate}`;
      metaRow.appendChild(auction);
    }
    if (item.postedOn) {
      const posted = document.createElement("span");
      posted.className = "card-meta-item";
      posted.innerHTML = `<strong>Posted</strong> ${item.postedOn}`;
      metaRow.appendChild(posted);
    }

    const details = document.createElement("p");
    details.className = "card-details";
    details.textContent = item.details || item.address || "No description available.";

    body.append(badges, title, location, price);
    if (metaRow.childElementCount) body.appendChild(metaRow);
    body.appendChild(details);

    if (item.image) {
      const imageWrap = document.createElement("div");
      imageWrap.className = "card-image";
      const img = document.createElement("img");
      img.loading = "lazy";
      img.src = item.image;
      img.alt = item.title;
      imageWrap.appendChild(img);
      card.appendChild(imageWrap);
    }

    card.appendChild(body);

    if (isValidListingUrl(item.link, item.source)) {
      const action = document.createElement("div");
      action.className = "card-action";
      const link = document.createElement("a");
      link.className = "card-link";
      link.href = item.link;
      link.target = "_blank";
      link.rel = "noopener noreferrer";
      link.textContent = "View listing";
      action.appendChild(link);
      card.appendChild(action);
    }

    elements.cards.appendChild(card);
  });
};

const clearFilters = () => {
  elements.sourceFilter.value = "";
  elements.cityFilter.value = "";
  elements.bankFilter.value = "";
  elements.typeFilter.value = "";
  elements.minPrice.value = "";
  elements.maxPrice.value = "";
  elements.searchInput.value = "";
  elements.photoOnly.checked = false;
  applyFilters();
};

const toggleSidebar = (open) => {
  const isOpen = open ?? !elements.sidebar.classList.contains("is-open");
  elements.sidebar.classList.toggle("is-open", isOpen);
  elements.filtersToggle.setAttribute("aria-expanded", String(isOpen));
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
  elements.refreshBtn.textContent = "Refreshing…";
  try {
    const data = await fetchJson();
    const raw = Array.isArray(data) ? data : [];
    const withUrl = raw.filter((item) =>
      isValidListingUrl(item.link || item.raw?.property_url, item.source || item.raw?.source)
    );
    listings = dedupeListings(withUrl.map(normalizeListing));
    elements.totalCount.textContent = String(listings.length);
    const emptyMsg = elements.emptyState.querySelector("p");
    if (emptyMsg) {
      emptyMsg.textContent = "Try clearing filters or widening your search.";
    }
    buildFilters();
    applyFilters();
    updateTimestamp();
  } catch (error) {
    elements.cards.innerHTML = "";
    elements.cards.classList.add("hidden");
    elements.emptyState.classList.remove("hidden");
    const msg = elements.emptyState.querySelector("p");
    if (msg) {
      msg.textContent =
        "Unable to load data. Run the scraper first, then refresh.";
    }
  } finally {
    elements.refreshBtn.disabled = false;
    elements.refreshBtn.textContent = "Refresh";
  }
};

[
  elements.sourceFilter,
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
elements.emptyClearBtn.addEventListener("click", () => {
  clearFilters();
  toggleSidebar(false);
});
elements.filtersToggle.addEventListener("click", () => toggleSidebar());

document.addEventListener("click", (e) => {
  if (
    window.innerWidth <= 900 &&
    elements.sidebar.classList.contains("is-open") &&
    !elements.sidebar.contains(e.target) &&
    !elements.filtersToggle.contains(e.target)
  ) {
    toggleSidebar(false);
  }
});

loadData();
