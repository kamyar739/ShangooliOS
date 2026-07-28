# ShangooliOS Todo

## Completed: Guided Replace Artwork

Add a compact **Replace Artwork** workflow for frequent source-image corrections:

- Keep one persistent five-stage guide: Replace Source, Quality, Rebuild Files,
  Review Mockups, and Update Shops.
- Preserve artwork writing, SEO, prices, variants, Printify IDs, Etsy IDs, and
  the current Etsy paused/live state.
- Reuse the existing certification, AI upscale, print, ratio, mockup,
  Printify-update, Etsy-sync, and recovery implementations.
- Require explicit visual approval before external synchronization.
- Support replacing and downloading an individual mockup from the review stage.
- Leave collection-card refreshes for other artworks as an explicit manual
  follow-up in Collection Review.

## Completed: Source and Mockup Downloads

Provide a download action beside the saved source and in every populated mockup
slot. Downloads must not trigger the page-level waiting indicator.

## Completed: Structured Artwork Metadata

Replace selected free-text Artwork Intelligence fields with controlled choices so analysis produces consistent metadata across collections:

- **Style:** dropdown with options such as Contemporary expressionist figurative oil painting, Modern abstract figurative, Impressionist, and Minimalist.
- **Mood:** dropdown or controlled multi-select with options such as Passionate, Joyful, Serene, Dramatic, Reflective, and Empowering.
- **Suggested Rooms:** checkboxes.
- **Target Customer:** checkboxes.

Update **Analyze Artwork** to select from these existing values rather than inventing new text. The intended benefits are more consistent metadata, stronger SEO, reliable filtering, and easier future automation.

## Completed: Artwork Intelligence Flow

Artwork Intelligence analysis requires an uploaded artwork image. Review the workflow order so the image upload clearly occurs before Artwork Intelligence. Consider moving the analysis interface to the Source or Quality stage, or otherwise making the upload dependency explicit, rather than presenting analysis before the required image exists.

Artwork Intelligence is also not producing useful creative metadata consistently. In the observed case, **Theme** remained empty and Analysis Notes contained only:

> Local analysis from source artwork. Orientation: vertical. Source dimensions: 4096 × 6144px. Review and refine the creative fields before using them for listing generation.

Investigate why analysis is returning only technical file information instead of populating the creative fields. The analysis should derive meaningful metadata from the approved image while using the planned controlled Style, Mood, Suggested Rooms, and Target Customer choices.

## Completed: Collection Card Image Cropping

On the Collections page, artwork cards crop vertical images too aggressively, cutting off the top and bottom and showing only the center. Update the card presentation so vertical artwork remains recognizable—prefer fitting the complete image within the thumbnail area or using an orientation-aware thumbnail treatment instead of a fixed center crop.

## Completed: Previous and Next Artwork Navigation

Add persistent **Previous artwork** and **Next artwork** controls near the top of every artwork page. Navigation should follow the artwork sequence within the current collection and preserve the current workflow step when practical, allowing the user to review consecutive artworks without returning to Collections or moving through unrelated application pages.

## Completed: Vertical Mockup Cropping

For vertical artwork, the **Close-up Detail** listing image and listing image 6, **Sizes and Ratios**, are being rendered as horizontal compositions. The top and bottom of the artwork are consequently cropped off. Make these mockup templates orientation-aware so vertical artwork uses a vertical frame/canvas and preserves the complete composition.

## Completed: Mockup Scene Selection

For each regeneratable mockup image, make the primary dropdown select the actual saved **Scene**, filtered to scenes compatible with the artwork’s vertical or horizontal orientation. The current **Template Style** dropdown is less useful because it does not clearly tell the user which room or background will be generated.

Keep Template Style only as a secondary control when it produces a meaningful visual difference, such as frame, mat, typography, or layout treatment. The intended per-image controls are:

1. Scene
2. Optional presentation style
3. Regenerate

This should make regeneration predictable and prevent users from having to find scene selection inside an advanced section.

## Completed: Collection Branding Mockup

Listing image 8, **Collection Branding**, is using the hard-coded Celebration Collection name for artwork in the Duende collection. Generate this image from the artwork’s actual collection record so the displayed collection name, identity, and related text always match the selected artwork’s collection.

The **Hero** mockup already works well visually, but it should include a subtle reference to the artwork’s collection—for example, “Part of the Duende Collection.” Keep the artwork as the visual focus and avoid turning the Hero image into a heavily branded graphic.

## Completed: Prepare Automatically Progress and Recovery

Investigate a reported hang when **Prepare Automatically** was selected for `DUE-004 — Rapture`. The UI and application appeared to stop responding.

The operation should:

- Show an accurate progress indicator for its entire duration.
- Identify the current preparation stage.
- Return a clear success or failure result.
- Time out safely when a background operation stalls.
- Allow the user to retry or recover without repeating completed work.

## Completed: Rapture Etsy Synchronization

Investigate the failed attempt to update the existing Etsy listing for `DUE-004 — Rapture`. Etsy synchronization returned:

> {"detail":"Review and approve the Etsy Standard mockup set before Etsy synchronization"}

The workflow should clearly show that mockup-set approval is required before Etsy synchronization, take the user directly to the required approval control, and avoid presenting the listing as ready to synchronize while that prerequisite is incomplete.

The synchronized Rapture listing also did not receive the expected Duende collection name/section on Etsy. Verify that synchronization creates or finds the Etsy section derived from the artwork’s current collection and assigns the listing to it. Collection renames and collection-code changes must not leave the listing associated with an older or incorrect Etsy section.

## Completed: AI Enhancement After Replacing a Source

Investigate the Quality step for the Dominion artwork after its source image was replaced. The interface offered only **Approve and continue** and did not provide **AI enhance 4×**.

Replacing a source image should completely reset the previous source’s certification and enhancement state. The newly uploaded source should be evaluated independently and, when its dimensions or quality qualify for enhancement, the 4× AI-enhancement option should become available again before approval.

## Completed: Collection Card Mockup

Create one reusable **Collection Card** for each collection and make it available in the Mockups section. The card should include:

- The collection name.
- A short collection description.
- Small thumbnails representing each artwork currently in the collection.
- Consistent ShangooliShop collection branding.

The card should update when artwork is added, replaced, renamed, archived, or reordered. It can serve as a collection-discovery image within an artwork’s Etsy gallery, replacing or improving the current generic Collection Branding mockup.

## Completed: Gallery-Based Collection Selector

On the Collections page, replace the collection dropdown with a visual gallery of collection cards, similar to the existing artwork gallery for an individual collection.

Selecting a collection card should:

- Clearly highlight the selected collection.
- Update the artwork gallery and collection details below to show that collection.
- Keep the user on the Collections page rather than navigating to a disconnected view.
- Preserve collection ordering and the existing drag-to-reorder capability.

Each selector card should provide enough visual identity—such as the collection name, description, status, and representative artwork thumbnails—to make choosing a collection easier than scanning a dropdown.

## Completed: Signature Collection Cover

Give every collection a dedicated **signature cover image** that serves as the visual identity of the complete collection.

This should not be one of the numbered, sellable artworks. It is a separate hero composition representing the collection’s overall story—the equivalent of a movie poster representing an entire film.

For Duende, the cover could eventually combine subtle visual elements from all six emotional stages into one striking composition. Use the signature cover consistently wherever the collection is presented:

- ShangooliOS collection gallery.
- Etsy collection graphics and banners.
- Pinterest pins.
- Instagram and other social posts.
- The future ShangooliShop website.
- Collection cards and promotional mockups.

Store the cover as a collection-level asset with its own upload, replacement, approval, and preview flow. Reusing one recognizable image across channels should build recognition for complete collections rather than only individual paintings.

This feature should reinforce the brand statement:

> **Every Collection Tells a Story.**

## Completed: Refresh Collection Branding Mockups

The **Collection Branding** listing image is repeated within every artwork's mockup set, but it includes thumbnails of the complete collection. When an approved source image is replaced, renamed, reordered, or retired, the repeated collection-branding cards for the other artworks can become stale.

Add a collection-level **Refresh Collection Cards** action that:

- Detects artwork changes that affect the shared collection card.
- Regenerates only the Collection Branding / Listing Image 8 card for selected affected artworks.
- Leaves all other mockups, print files, artwork text, prices, Printify products, Etsy state, and user edits unchanged.
- Marks only successfully refreshed cards for visual reapproval.
- Reports per-artwork success or failure and preserves a previous card if regeneration fails.

## Completed: Clear Mockup Approval State

After a curated mockup set has been approved, the interface still shows a checked review box and an active-looking **Set approved** button. Replace this with an unambiguous approved state, such as a non-interactive **Approved** indicator. Make it clear when review is still required versus when no further approval action is needed.

## Completed: Detect Unsynced Etsy Images

Changing and approving a listing mockup updates local artwork state but currently leaves the workflow tabs showing **Listing**, **Printify**, and **Publish** as completed. The application should detect that the live Etsy gallery is now stale.

- Keep local Listing and Printify completion intact when only listing images change.
- Mark Publish as **Unpublished Etsy image changes** until the current approved mockup set is synchronized.
- Surface a clear Etsy-only synchronization action.
- Do not recreate or alter the Printify product, variants, prices, writing, or other existing external state.

## Completed: Guided Replace Mockup

Add a compact workflow for correcting one or more listing images:

- Replace only the affected mockup slots.
- Review and approve the complete ordered gallery.
- Synchronize only the approved Etsy images when a linked listing is stale.
- Preserve the source, print files, writing, price, variants, Printify product, and Etsy live or paused state.
