// Our docs are proxied through to canonical.com/juju/docs/ops.
// If multiple doc versions are configured, Read the Docs renders a version switcher.
// The version switcher has the readthedocs-hosted.com URL in links, which we don't want,
// so this script overwrites those links to use the correct public-facing URL.

// Replace oldDomain with newDomain
const oldDomain = 'canonical-juju-ops.readthedocs-hosted.com';
const newDomain = 'canonical.com/juju/docs/ops';

// Use a MutationObserver to wait for the RTD flyout element to appear in the DOM
const observer = new MutationObserver(function(mutations, obs) {
    const rtdFlyout = document.querySelector('readthedocs-flyout');
    if (!rtdFlyout) return;

    obs.disconnect();

    rtdFlyout.addEventListener('click', function() {
        const shadowRoot = rtdFlyout.shadowRoot;
        if (!shadowRoot) return;

        const anchors = shadowRoot.querySelectorAll('a');
        anchors.forEach(anchor => {
            anchor.href = anchor.href.replace(new RegExp(oldDomain, 'g'), newDomain);
        });
    });
});

observer.observe(document.body, { childList: true, subtree: true });
