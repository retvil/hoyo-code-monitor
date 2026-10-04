// Experiment page placeholder — theme toggle fallback (main logic lives inline in dashboard_experiment.html).
document.addEventListener('DOMContentLoaded', () => {
  const btn = document.getElementById('theme-toggle');
  if (btn && !btn.dataset.bound) {
    btn.dataset.bound = '1';
    btn.addEventListener('click', () => document.documentElement.classList.toggle('dark'));
  }
});
