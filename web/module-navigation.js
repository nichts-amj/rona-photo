// Deep links from the launcher open the existing History view.
function openLinkedHistory(){
  if(location.hash === '#history') document.getElementById('nav-history')?.click();
}
window.addEventListener('DOMContentLoaded',openLinkedHistory);
window.addEventListener('hashchange',openLinkedHistory);
