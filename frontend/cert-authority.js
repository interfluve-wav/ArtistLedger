/**
 * Certificate display authority — pure logic, no DOM.
 *
 * The finalized on-chain contract verdict is the sole authority for the
 * VRFD seal, "verified" label, and primary score. A NOT VERIFIED result
 * can never produce a VRFD seal, verified label, or replacement score —
 * even when a lenient/friendly projection would clear its own threshold.
 *
 * Usable from the browser (window.CertAuthority) and from Node tests
 * (module.exports). Keep this file free of DOM / GenLayer dependencies.
 */
(function (root, factory) {
  if (typeof module === "object" && module.exports) {
    module.exports = factory();
  } else {
    root.CertAuthority = factory();
  }
})(typeof self !== "undefined" ? self : this, function () {
  "use strict";

  var FRIENDLY_THRESHOLD = 60;

  /**
   * Compute the informational lenient projection (demo overlay only).
   * Never used to flip seal / verified label / primary score.
   */
  function friendlyProjection(data) {
    var e = (data && data.evidence) || {};
    var tier1Count =
      (e.acoustid_matched ? 1 : 0) +
      (e.spotify_artist_id ? 1 : 0) +
      (e.apple_music_artist_id ? 1 : 0);
    var tier2Count =
      (e.bandcamp_handle ? 1 : 0) +
      (e.soundcloud_handle ? 1 : 0) +
      (e.instagram_handle ? 1 : 0) +
      (e.lastfm_scrobble_count !== undefined && e.lastfm_scrobble_count !== null ? 1 : 0);
    var matchCount = Number((data && data.matchCount) || 0);
    var llmBonus = Math.max(0, Number(e.press_narrative_score || 0));
    var friendly = Math.min(
      100,
      (tier1Count >= 2 ? 55 : tier1Count === 1 ? 35 : 0) +
        (tier2Count > 0 ? 20 : 0) +
        (matchCount >= 2 ? 10 : 0) +
        Math.min(llmBonus, 5) +
        5
    );
    return {
      friendly: friendly,
      friendlyWouldPass: friendly >= FRIENDLY_THRESHOLD,
      tier1Count: tier1Count,
      tier2Count: tier2Count,
      llmBonus: llmBonus,
    };
  }

  /**
   * Resolve seal / label / scores from a parsed receipt.
   *
   * @param {{ verdict: string, score: number|null, matchCount?: number, evidence?: object }} data
   * @returns {object} display fields; `ok` is true ONLY when verdict === "VERIFIED"
   */
  function resolveCertificateDisplay(data) {
    data = data || {};
    var verdict = data.verdict || "?";
    var onChainVerified = verdict === "VERIFIED";
    var onChainScore = data.score;
    var matchCount = Number(data.matchCount || 0);
    var proj = friendlyProjection(data);

    // Authoritative: finalized contract verdict only.
    var ok = onChainVerified;
    var seal = ok ? "VRFD" : "—";
    var subtitle = ok
      ? "verified · " + matchCount + " of 2 sources matched"
      : "not verified · " + matchCount + " of 2 sources matched";
    // Primary score is always the on-chain score — never replaced by friendly.
    var displayScore = onChainScore != null ? onChainScore : "?";
    var badge = ok ? "VRFD" : verdict;
    var scoreLine =
      (onChainScore != null ? onChainScore : "?") +
      "/100 on-chain · " +
      proj.friendly +
      "/100 lenient (info) · " +
      (ok ? "VRFD" : "NOT VRFD");

    return {
      ok: ok,
      seal: seal,
      subtitle: subtitle,
      displayScore: displayScore,
      badge: badge,
      scoreLine: scoreLine,
      onChainScore: onChainScore,
      onChainVerified: onChainVerified,
      friendly: proj.friendly,
      friendlyWouldPass: proj.friendlyWouldPass,
      tier1Count: proj.tier1Count,
      tier2Count: proj.tier2Count,
      llmBonus: proj.llmBonus,
      matchCount: matchCount,
      FRIENDLY_THRESHOLD: FRIENDLY_THRESHOLD,
    };
  }

  return {
    FRIENDLY_THRESHOLD: FRIENDLY_THRESHOLD,
    friendlyProjection: friendlyProjection,
    resolveCertificateDisplay: resolveCertificateDisplay,
  };
});
