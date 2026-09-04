"use client";

import { useCallback, useState } from "react";
import { FileDown, Loader2 } from "lucide-react";
import { Button } from "@/components/ui/button";
import type { Answer } from "@/lib/contract";

/**
 * Download the answer as a real PDF file (S22).
 *
 * This REPLACES a button that opened the print dialog. Print-to-PDF was an honest
 * half-step — and it was labelled honestly — but it is not what "download" means: it hands
 * the reader a system dialog and asks them to finish the job.
 *
 * jsPDF is ~350kB, against ~22kB of headroom on `/`. It stays out of the initial bundle
 * entirely because the import is DYNAMIC: nothing is fetched until someone actually clicks
 * download, which most readers never will. A static import would have blown the budget and
 * made every visitor pay for a feature used by a few.
 *
 * SOURCES ARE PART OF THE DOCUMENT, not an afterthought. A medical paragraph saved to disk
 * with its "[1]" markers intact and no key for them is less trustworthy than the original
 * and looks like it came from nowhere — the exact opposite of what this product is for.
 */
export function DownloadPdf({ answer, question }: { answer: Answer; question: string }) {
  const [state, setState] = useState<"idle" | "working" | "failed">("idle");

  const download = useCallback(async () => {
    setState("working");
    try {
      // Dynamic: this is the whole reason the bundle budget survives.
      const { jsPDF } = await import("jspdf");
      const doc = new jsPDF({ unit: "pt", format: "a4" });

      const M = 56; // margin
      const W = doc.internal.pageSize.getWidth() - M * 2;
      const H = doc.internal.pageSize.getHeight();
      let y = M;

      // Paginate by hand. jsPDF does not flow text across pages, so writing a long answer
      // without this silently prints past the bottom edge and loses it.
      const write = (text: string, size: number, style: "normal" | "bold", gap = 6) => {
        doc.setFont("helvetica", style);
        doc.setFontSize(size);
        for (const line of doc.splitTextToSize(text, W) as string[]) {
          if (y > H - M) {
            doc.addPage();
            y = M;
          }
          doc.text(line, M, y);
          y += size + gap * 0.4;
        }
        y += gap;
      };

      write("Medical Reference Assistant", 10, "normal", 2);
      write(question, 16, "bold", 10);
      write(answer.text, 11, "normal", 12);

      if (answer.citations.length) {
        write("Sources", 12, "bold", 6);
        answer.citations.forEach((c, i) => {
          write(`[${i + 1}] ${c.source}${c.page !== null ? `, p.${c.page}` : ""}`, 10, "normal", 2);
        });
      }

      // The disclaimer travels with the file. A PDF outlives the page it came from and gets
      // forwarded to people who never saw the interface or its warnings.
      y += 10;
      write(
        "General information, not medical advice. This assistant answers only from a medical " +
          "reference corpus. It cannot diagnose, prescribe, or replace a clinician. " +
          `Generated ${new Date().toLocaleDateString()}.`,
        8,
        "normal",
      );

      const slug =
        question
          .toLowerCase()
          .replace(/[^a-z0-9]+/g, "-")
          .replace(/^-|-$/g, "")
          .slice(0, 48) || "answer";
      doc.save(`${slug}.pdf`);
      setState("idle");
    } catch {
      // A blocked download, a failed chunk fetch, or no disk. Reported rather than
      // swallowed: a button that appears to do nothing is worse than one that says it
      // could not.
      setState("failed");
      setTimeout(() => setState("idle"), 3000);
    }
  }, [answer, question]);

  return (
    <Button variant="ghost" size="sm" onClick={() => void download()} disabled={state === "working"}>
      {state === "working" ? (
        <Loader2 className="size-3.5 animate-spin" aria-hidden="true" />
      ) : (
        <FileDown className="size-3.5" aria-hidden="true" />
      )}
      {state === "working" ? "Preparing…" : state === "failed" ? "Download failed" : "Download PDF"}
      <span className="sr-only" role="status" aria-live="polite">
        {state === "failed" ? "Could not create the PDF" : ""}
      </span>
    </Button>
  );
}
