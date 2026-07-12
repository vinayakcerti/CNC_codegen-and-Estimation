// Rate-card admin modal (ARD R3 §6.5): thin .qm-backdrop/.qm-modal chrome
// around RateCardEditor — the same editor renders inline on the Shop
// Library screen. External props and behavior are unchanged (App.tsx
// mounts this exactly as before).
import { RateCardEditor } from "./RateCardEditor";
import type { CostingProfile, RateCardBreakdown } from "./costing";

export function CostLibraryPanel({
  profile,
  currency,
  partHoles = null,
  onClose,
  onChanged,
}: {
  profile: CostingProfile;
  currency: string;
  // The loaded part's hole lookups (rate-card breakdown) — surfaces a
  // "confirm what you quote" list so the shop signs off the operations of
  // THIS part first; the full library below is for everything else.
  partHoles?: RateCardBreakdown["holes"] | null;
  onClose: () => void;
  // Bump a nonce in the parent so estimates re-read the stored profile.
  onChanged: () => void;
}) {
  return (
    <div className="qm-backdrop" onClick={onClose}>
      <div
        className="qm-modal"
        style={{ maxWidth: 860, width: "94vw" }}
        onClick={(e) => e.stopPropagation()}
      >
        <div style={{ display: "flex", alignItems: "center", gap: 8 }}>
          <h3 style={{ margin: "0 0 2px" }}>Rate card — {profile.name}</h3>
          <span style={{ flex: 1 }} />
          <button className="btn" onClick={onClose}>✕ Close</button>
        </div>
        <RateCardEditor
          profile={profile}
          currency={currency}
          partHoles={partHoles}
          onChanged={onChanged}
        />
      </div>
    </div>
  );
}
