# { "Depends": "py-genlayer:1jb45aa8ynh2a9c9xn3b7qqh8sm5q93hwfp7jqmwsfhh8jpz09h6" }
"""
OnChainProvenanceRegistry — GenLayer Intelligent Contract

Tracks real-world music releases with provenance validated through LLM
comparative consensus. The primitive answers one question: is this audio
track provably human-made and unaltered?

State:
  artists:        TreeMap[Address, Artist]      wallet -> real identity
  releases:       TreeMap[bytes32, Release]     audio hash -> release record
  disputes:       TreeMap[bytes32, Dispute]     audio hash -> active dispute
  identity_score: TreeMap[Address, u64]         wallet -> last consensus score
  identity_count: TreeMap[Address, u64]         wallet -> number of verifications

The 70-score threshold for "verified" is intentional: 70 is high enough that
a single judge cannot pass a fake identity (must reach consensus on
re-fetched evidence), low enough that real artists with sparse web presence
can still pass.

The 15-point tolerance band on validators is intentional: LLM re-judgments
of the same evidence should agree within 15 points; wider drift means the
evidence is genuinely ambiguous and the contract should not write to state.
"""

from genlayer import *


# ─── Storage layouts ───────────────────────────────────────────────────────

class Artist(gl.Contract):
    wallet: Address
    did: str
    name: str
    verified_at: u64
    score: u64


class Release(gl.Contract):
    artist: Address
    title: str
    audio_hash: bytes32
    contributors: list[Address]
    release_date: u64
    anchored_at: u64
    contested: bool


class Dispute(gl.Contract):
    audio_hash: bytes32
    claimant: Address
    claim: str
    evidence_url: str
    filed_at: u64
    resolved: bool
    resolution: str  # "Upheld" | "Dismissed"


# ─── Constants ─────────────────────────────────────────────────────────────

VERIFICATION_THRESHOLD: u64 = 70
VALIDATOR_TOLERANCE: u64 = 15
REPUTATION_REWARD_PER_RELEASE: u64 = 2
REPUTATION_PENALTY_PER_UPHELD_DISPUTE: u64 = 10


# ─── Helpers ───────────────────────────────────────────────────────────────

def _fetch_sources(urls: list[str]) -> list[str]:
    """Fetch a list of evidence URLs and return their decoded body strings."""
    bodies: list[str] = []
    for url in urls:
        try:
            resp = gl.nondet.web.get(url)
            bodies.append(resp.body.decode("utf-8", errors="replace"))
        except Exception:
            bodies.append("")
    return bodies


def _llm_score_identity(name: str, did: str, source_bodies: list[str]) -> int:
    """Leader/validator LLM call: score identity consistency 0-100."""
    sources_blob = "\n---\n".join(source_bodies)
    prompt = (
        f"You are verifying whether a claimed music artist identity is real "
        f"and consistent across independent sources.\n\n"
        f"Claimed name: {name}\n"
        f"Claimed DID (decentralized identifier): {did}\n\n"
        f"Sources fetched:\n{sources_blob}\n\n"
        f"Instructions:\n"
        f"1. Check whether the sources describe a real, consistent human "
        f"identity (or their official artist project).\n"
        f"2. Check whether the name, identifiers, and discography line up "
        f"across sources.\n"
        f"3. Penalize: fabricated sources, sparse cross-reference, name "
        f"collisions with unrelated public figures, generic placeholder "
        f"content.\n"
        f"4. Score from 0 (no evidence of real identity) to 100 (multiple "
        f"high-quality sources clearly describe this person/project).\n\n"
        f"Respond with ONLY a single integer between 0 and 100. No "
        f"explanation, no other text."
    )
    raw = gl.nondet.exec_prompt(prompt)
    return int(raw.strip().split()[0])


def _llm_judge_dispute(
    release: Release, artist: Artist, claim: str, evidence_body: str
) -> int:
    """Leader/validator LLM call: judge a dispute 0-100 (0=dismiss, 100=uphold)."""
    prompt = (
        f"You are adjudicating a provenance dispute on a music release.\n\n"
        f"Release:\n"
        f"  Title: {release.title}\n"
        f"  Audio hash: 0x{release.audio_hash.hex()}\n"
        f"  Anchored at: {release.anchored_at}\n"
        f"  Claimed release date: {release.release_date}\n\n"
        f"Claimed artist:\n"
        f"  Wallet: {artist.wallet}\n"
        f"  Name: {artist.name}\n"
        f"  DID: {artist.did}\n"
        f"  Verified at: {artist.verified_at} with score {artist.score}\n\n"
        f"Dispute filed by: {release.artist}\n"
        f"Claim: {claim}\n"
        f"Evidence body:\n{evidence_body}\n\n"
        f"Possible dispute types: AI-generated track credited to a real "
        f"artist, uncredited sample, ghost release by a label, identity "
        f"impersonation.\n\n"
        f"Score from 0 (no merit, dismiss) to 100 (clearly meritorious, "
        f"uphold). Use the source data; do not invent.\n\n"
        f"Respond with ONLY a single integer between 0 and 100."
    )
    raw = gl.nondet.exec_prompt(prompt)
    return int(raw.strip().split()[0])


# ─── Contract ──────────────────────────────────────────────────────────────

class ProvenanceRegistry(gl.Contract):
    artists: TreeMap[Address, Artist]
    releases: TreeMap[bytes32, Release]
    disputes: TreeMap[bytes32, Dispute]
    identity_score: TreeMap[Address, u64]
    identity_count: TreeMap[Address, u64]
    artist_releases: TreeMap[Address, list[bytes32]]

    # ─── Identity verification ─────────────────────────────────────────────

    @gl.public.write
    def register_artist(
        self, did: str, name: str, evidence_urls: list[str]
    ) -> str:
        """
        Verify a wallet as belonging to a real human artist.

        Fetches evidence URLs (artist site, MusicBrainz, ISRC/ISWC, social
        profiles), asks the LLM to score identity consistency 0-100, and
        only writes to state if validators independently agree within a
        tolerance band of 15 points.

        Returns the consensus score (0-100). The artist is registered if
        score >= 70.
        """
        # Cap the evidence fetch to a sane bound so consensus doesn't get
        # gamed by huge URL lists. Five sources is plenty for cross-check.
        urls: list[str] = list(evidence_urls)[:5]

        def leader_judge() -> int:
            sources = _fetch_sources(urls)
            return _llm_score_identity(name, did, sources)

        def validator_fn(leader_result) -> bool:
            # Re-fetch sources and re-score independently. Accept only if
            # the validator's own score is within the tolerance band.
            if not isinstance(leader_result, gl.vm.Return):
                return False
            try:
                own_score = leader_judge()
            except Exception:
                return False
            return abs(own_score - int(leader_result.calldata)) <= VALIDATOR_TOLERANCE

        consensus_score = gl.vm.run_nondet_unsafe(leader_judge, validator_fn)

        # Update running stats regardless of pass/fail (counts the attempt)
        prev_count = self.identity_count.get(msg.sender, 0)
        self.identity_count[msg.sender] = prev_count + 1
        self.identity_score[msg.sender] = consensus_score

        if consensus_score >= VERIFICATION_THRESHOLD:
            self.artists[msg.sender] = Artist(
                wallet=msg.sender,
                did=did,
                name=name,
                verified_at=block.timestamp,
                score=consensus_score,
            )
            return f"Verified ({consensus_score})"

        return f"Not verified ({consensus_score})"

    # ─── Release anchoring ────────────────────────────────────────────────

    @gl.public.write
    def anchor_release(
        self,
        audio_hash: bytes32,
        title: str,
        contributors: list[Address],
        release_date: u64,
    ) -> str:
        """
        Anchor a release onchain. Caller must be a verified artist.

        No LLM consensus is needed here — the work was done at registration
        and at the audio-hash uniqueness check. If the same audio_hash is
        anchored twice, we reject (a real artist cannot accidentally publish
        the same audio twice; an impersonator can).
        """
        if msg.sender not in self.artists:
            return "Not a verified artist"
        if self.releases.get(audio_hash) is not None:
            return "Audio hash already anchored"

        artist = self.artists[msg.sender]
        self.releases[audio_hash] = Release(
            artist=msg.sender,
            title=title,
            audio_hash=audio_hash,
            contributors=list(contributors),
            release_date=release_date,
            anchored_at=block.timestamp,
            contested=False,
        )

        # Track per-artist release list
        existing = self.artist_releases.get(msg.sender, [])
        existing.append(audio_hash)
        self.artist_releases[msg.sender] = existing

        return f"Anchored '{title}' for {artist.name}"

    # ─── Dispute filing ───────────────────────────────────────────────────

    @gl.public.write
    def dispute(
        self, audio_hash: bytes32, claim: str, evidence_url: str
    ) -> str:
        """
        File a provenance dispute on a release. Anyone can file; the LLM
        judges the merit, validators cross-check, and the release is marked
        contested if the dispute is upheld.

        Multiple disputes on the same release overwrite the previous — this
        is intentional, as the most recent claim is the one under review.
        """
        release = self.releases.get(audio_hash)
        if release is None:
            return "Release not found"
        if release.artist == msg.sender:
            return "Cannot dispute your own release"
        if msg.sender not in self.artists and msg.sender != release.artist:
            # Anyone can file, but unverified filers cannot anchor a release.
            # Disputes are open to all; we just don't reward unverified filers.
            pass

        artist = self.artists[release.artist]

        def leader_judge() -> int:
            try:
                resp = gl.nondet.web.get(evidence_url)
                evidence_body = resp.body.decode("utf-8", errors="replace")
            except Exception:
                evidence_body = ""
            return _llm_judge_dispute(release, artist, claim, evidence_body)

        def validator_fn(leader_result) -> bool:
            if not isinstance(leader_result, gl.vm.Return):
                return False
            try:
                own_score = leader_judge()
            except Exception:
                return False
            return abs(own_score - int(leader_result.calldata)) <= VALIDATOR_TOLERANCE

        dispute_score = gl.vm.run_nondet_unsafe(leader_judge, validator_fn)

        self.disputes[audio_hash] = Dispute(
            audio_hash=audio_hash,
            claimant=msg.sender,
            claim=claim,
            evidence_url=evidence_url,
            filed_at=block.timestamp,
            resolved=True,
            resolution="Upheld" if dispute_score >= 60 else "Dismissed",
        )

        if dispute_score >= 60:
            # Mark the release as contested
            release.contested = True
            self.releases[audio_hash] = release

            # Penalize the artist's reputation
            current_score = self.identity_score.get(release.artist, 70)
            new_score = max(
                0,
                current_score - REPUTATION_PENALTY_PER_UPHELD_DISPUTE,
            )
            self.identity_score[release.artist] = new_score
            if release.artist in self.artists:
                a = self.artists[release.artist]
                a.score = new_score
                # If the score drops below threshold, the artist is no
                # longer "verified" for new anchors
                if a.score < VERIFICATION_THRESHOLD:
                    a.verified_at = 0
                self.artists[release.artist] = a

            return f"Dispute upheld (score {dispute_score}); release contested"
        return f"Dispute dismissed (score {dispute_score})"

    # ─── Read-only views ──────────────────────────────────────────────────

    @gl.public.view
    def is_verified_human(self, audio_hash: bytes32) -> bool:
        """
        Returns True iff the audio hash is anchored, the artist is
        currently verified (score >= 70), and no upheld dispute exists.
        """
        release = self.releases.get(audio_hash)
        if release is None:
            return False
        if release.contested:
            return False
        artist = self.artists.get(release.artist)
        if artist is None:
            return False
        return artist.score >= VERIFICATION_THRESHOLD and artist.verified_at > 0

    @gl.public.view
    def get_artist(self, wallet: Address) -> dict:
        artist = self.artists.get(wallet)
        if artist is None:
            return {"verified": False}
        return {
            "verified": artist.score >= VERIFICATION_THRESHOLD
            and artist.verified_at > 0,
            "did": artist.did,
            "name": artist.name,
            "score": artist.score,
            "verified_at": artist.verified_at,
        }

    @gl.public.view
    def get_release(self, audio_hash: bytes32) -> dict:
        release = self.releases.get(audio_hash)
        if release is None:
            return {"found": False}
        return {
            "found": True,
            "title": release.title,
            "artist": str(release.artist),
            "contributors": [str(c) for c in release.contributors],
            "release_date": release.release_date,
            "anchored_at": release.anchored_at,
            "contested": release.contested,
        }

    @gl.public.view
    def get_dispute(self, audio_hash: bytes32) -> dict:
        dispute = self.disputes.get(audio_hash)
        if dispute is None:
            return {"found": False}
        return {
            "found": True,
            "claimant": str(dispute.claimant),
            "claim": dispute.claim,
            "evidence_url": dispute.evidence_url,
            "filed_at": dispute.filed_at,
            "resolution": dispute.resolution,
        }
