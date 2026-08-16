document.addEventListener('DOMContentLoaded', () => {
  document.querySelectorAll('div.admonition[id^="best-practice-"]').forEach((el) => {
    const title = el.querySelector('.admonition-title');
    if (!title) return;
    const a = document.createElement('a');
    a.className = 'headerlink';
    a.href = '#' + el.id;
    a.title = 'Link to this best practice';
    a.textContent = '¶';
    title.appendChild(a);
  });
});
