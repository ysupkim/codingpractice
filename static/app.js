const fileInput = document.getElementById('fileInput');
const uploadBtn = document.getElementById('uploadBtn');
const uploadStatus = document.getElementById('uploadStatus');
const productCount = document.getElementById('productCount');
const productsTableBody = document.querySelector('#productsTable tbody');
const runSearchBtn = document.getElementById('runSearchBtn');
const searchStatus = document.getElementById('searchStatus');
const resultsTableBody = document.querySelector('#resultsTable tbody');
const showAll = document.getElementById('showAll');
const downloadBtn = document.getElementById('downloadBtn');
const warningsBox = document.getElementById('warningsBox');
const debugTableBody = document.querySelector('#debugTable tbody');
const searchDebugTableBody = document.querySelector('#searchDebugTable tbody');
const summaryList = document.getElementById('summaryList');

let cachedResults = [];

function renderWarnings(warnings) {
  warningsBox.innerHTML = '';
  (warnings || []).forEach((w) => {
    const div = document.createElement('div');
    div.className = 'warning';
    div.textContent = `주의: ${w}`;
    warningsBox.appendChild(div);
  });
}

function renderSummary(summary) {
  const s = summary || {};
  summaryList.innerHTML = `
    <li>문제 결과 있음: ${s.problem_products || 0}개 제품</li>
    <li>API 호출 제한: ${s.rate_limit_products || 0}개 제품</li>
    <li>검색 결과 없음: ${s.no_result_products || 0}개 제품</li>
  `;
}

function renderProducts(products) {
  productCount.textContent = products.length;
  productsTableBody.innerHTML = '';
  (products || []).forEach((p) => {
    const tr = document.createElement('tr');
    tr.innerHTML = `<td>${p.name}</td><td>${p.online_discount_price.toLocaleString()}</td>`;
    productsTableBody.appendChild(tr);
  });
}

function renderDebugRows(debugRows) {
  debugTableBody.innerHTML = '';
  (debugRows || []).forEach((d) => {
    const tr = document.createElement('tr');
    const parsedText = d.parsed_price == null ? '(파싱 실패)' : d.parsed_price.toLocaleString();
    tr.innerHTML = `<td>${d.row_number}</td><td>${d.product_name}</td><td>${d.raw_price_value || ''}</td><td>${d.cleaned_price_value || ''}</td><td>${parsedText}</td>`;
    debugTableBody.appendChild(tr);
  });
}

function renderSearchDebugSummaries(summaries) {
  searchDebugTableBody.innerHTML = '';
  (summaries || []).forEach((s) => {
    const tr = document.createElement('tr');
    const note = s.piece_rule_all_dropped
      ? '검색 결과는 있었지만 피스 수 규칙 때문에 제외됨'
      : Object.entries(s.reasons || {}).map(([k, v]) => `${k}:${v}`).join(', ');

    tr.innerHTML = `<td>${s.product_name}</td><td>${s.pages_called || 0}</td><td>${s.accumulated_raw_count || s.raw_count || 0}</td><td>${s.passed_count}</td><td>${s.dropped_count}</td><td>${note || '-'}</td>`;
    searchDebugTableBody.appendChild(tr);
  });
}

function renderResults(results) {
  resultsTableBody.innerHTML = '';
  let sorted = [...(results || [])].sort((a, b) => {
    if (a.base_product_name === b.base_product_name) return (a.found_product_name || '').localeCompare(b.found_product_name || '');
    return a.base_product_name.localeCompare(b.base_product_name);
  });

  let prevBase = null;
  sorted.forEach((r) => {
    if (prevBase !== r.base_product_name) {
      const g = document.createElement('tr');
      g.innerHTML = `<td colspan="7" style="background:#eef2ff;font-weight:bold;">${r.base_product_name}</td>`;
      resultsTableBody.appendChild(g);
      prevBase = r.base_product_name;
    }

    const tr = document.createElement('tr');
    const priceText = r.sale_price == null ? '-' : r.sale_price.toLocaleString();
    const link = r.product_link ? `<a href="${r.product_link}" target="_blank">열기</a>` : '-';

    tr.innerHTML = `
      <td>${r.base_product_name}</td>
      <td>${r.base_online_discount_price.toLocaleString()}</td>
      <td>${r.found_product_name || '-'}</td>
      <td>${priceText}</td>
      <td>${r.mall_name || '-'}</td>
      <td>${link}</td>
      <td>${r.status || '-'}</td>
    `;
    resultsTableBody.appendChild(tr);
  });
}

function applyFilter() {
  if (showAll.checked) {
    renderResults(cachedResults);
  } else {
    renderResults(cachedResults.filter((r) => r.is_problem));
  }
}

uploadBtn.addEventListener('click', async () => {
  const file = fileInput.files[0];
  if (!file) {
    uploadStatus.textContent = '파일을 선택해주세요.';
    return;
  }

  uploadStatus.textContent = '업로드 중...';
  const formData = new FormData();
  formData.append('file', file);

  const res = await fetch('/upload', { method: 'POST', body: formData });
  const data = await res.json();

  if (!res.ok || !data.ok) {
    uploadStatus.textContent = `실패: ${data.message || '알 수 없는 오류'}`;
    return;
  }

  uploadStatus.textContent = `업로드 성공! (${data.product_count}개)`;
  renderProducts(data.products || []);
  renderWarnings(data.warnings || []);
  renderDebugRows(data.price_debug_rows || []);
  cachedResults = [];
  renderResults([]);
  renderSearchDebugSummaries([]);
  renderSummary({});
  searchStatus.textContent = '';
});

runSearchBtn.addEventListener('click', async () => {
  searchStatus.textContent = '검색 실행 중...';

  const res = await fetch('/run-search', { method: 'POST' });
  const data = await res.json();

  if (!res.ok || !data.ok) {
    searchStatus.textContent = `실패: ${data.message || '알 수 없는 오류'}`;
    return;
  }

  cachedResults = data.results || [];
  searchStatus.textContent = `검색 완료: ${data.count}건 / ${data.mode || ''}`;
  renderWarnings(data.warnings || []);
  renderSearchDebugSummaries(data.debug_summaries || []);
  renderSummary(data.summary_counts || {});
  applyFilter();
});

showAll.addEventListener('change', applyFilter);

downloadBtn.addEventListener('click', () => {
  const qs = showAll.checked ? '?show_all=true' : '';
  window.location.href = '/download' + qs;
});
