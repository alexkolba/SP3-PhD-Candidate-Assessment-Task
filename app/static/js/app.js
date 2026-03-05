// Markdown-lite renderer for output text
document.addEventListener('DOMContentLoaded', () => {
  document.querySelectorAll('.output-body').forEach(el => {
    el.innerHTML = renderMd(el.textContent);
  });
});

function renderMd(text) {
  return text
    .replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;')
    // Bold
    .replace(/\*\*(.+?)\*\*/g, '<strong>$1</strong>')
    // Headings
    .replace(/^#{1,3} (.+)$/gm, '<span class="md-heading">$1</span>')
    // Numbered lists
    .replace(/^\d+\.\s+(.+)$/gm, '<span class="md-li-num">$1</span>')
    // Bullet lists
    .replace(/^[-•]\s+(.+)$/gm, '<span class="md-li">$1</span>')
    // Double newline → paragraph break
    .replace(/\n\n/g, '\n<br>\n')
    .replace(/\n/g, '\n');
}
