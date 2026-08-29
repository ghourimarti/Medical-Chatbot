"use client";

import { FileDown } from "lucide-react";
import { Button } from "@/components/ui/button";

/**
 * Save the conversation as a PDF (F3).
 *
 * WHY `window.print()` AND NOT A PDF LIBRARY. jsPDF is ~100kB against ~23kB of headroom on
 * `/`, and the bundle budget is not the strongest argument against it — REDRAWING is. A
 * library rebuilds the answer from scratch, which loses the real typography, the citation
 * markers, and the text layer that makes a saved answer searchable and selectable. The
 * browser's own "Save as PDF" keeps all three, costs zero bytes, and honours the reader's
 * paper size and margins instead of guessing them.
 *
 * The trade, stated plainly: this opens the print dialog rather than dropping a file in
 * the downloads folder, so the LABEL says so. Calling it "Download PDF" and then showing a
 * print dialog would be a small lie, and a product whose whole claim is "we show you where
 * the answer came from" cannot afford small lies in its own UI.
 *
 * What reaches the paper is decided in the `@media print` block in globals.css: sidebar
 * and header removed, dark themes forced back to high-contrast light (browsers drop
 * backgrounds by default, so a dark surface would print as unreadable pale-on-white), and
 * evidence forced OPEN — a collapsed <details> prints collapsed, which would silently drop
 * the sources from a medical document.
 */
export function SavePdf() {
  return (
    <Button
      variant="ghost"
      size="sm"
      onClick={() => window.print()}
      title="Opens your browser's print dialog, where 'Save as PDF' is a destination"
    >
      <FileDown className="size-3.5" aria-hidden="true" />
      Print / Save as PDF
    </Button>
  );
}
