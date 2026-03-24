const fs = require("fs");
const path = require("path");
const docx = require("docx");

const {
  Document, Packer, Paragraph, TextRun, Table, TableRow, TableCell,
  WidthType, AlignmentType, HeadingLevel, BorderStyle, PageNumber,
  Header, Footer, TableOfContents, PageBreak, LevelFormat,
  convertInchesToTwip, ShadingType, Tab, TabStopType, TabStopPosition
} = docx;

// ── Markdown parser ──

function parseMd(text) {
  const lines = text.split("\n");
  const blocks = [];
  let i = 0;

  while (i < lines.length) {
    const line = lines[i];

    // blank
    if (line.trim() === "") { i++; continue; }

    // horizontal rule
    if (/^---+\s*$/.test(line.trim())) { i++; continue; }

    // code block
    if (line.trim().startsWith("```")) {
      i++;
      const codeLines = [];
      while (i < lines.length && !lines[i].trim().startsWith("```")) {
        codeLines.push(lines[i]);
        i++;
      }
      i++; // skip closing ```
      blocks.push({ type: "code", content: codeLines.join("\n") });
      continue;
    }

    // heading
    const hm = line.match(/^(#{1,6})\s+(.*)/);
    if (hm) {
      blocks.push({ type: "heading", level: hm[1].length, text: hm[2].trim() });
      i++;
      continue;
    }

    // table
    if (line.includes("|") && i + 1 < lines.length && /^\|[\s\-:|]+\|/.test(lines[i + 1].trim())) {
      const headerCells = line.split("|").filter(c => c.trim() !== "").map(c => c.trim());
      i += 2; // skip header + separator
      const rows = [headerCells];
      while (i < lines.length && lines[i].includes("|") && lines[i].trim() !== "") {
        const cells = lines[i].split("|").filter(c => c.trim() !== "").map(c => c.trim());
        rows.push(cells);
        i++;
      }
      blocks.push({ type: "table", rows });
      continue;
    }

    // bullet list
    if (/^\s*[-*]\s+/.test(line)) {
      const items = [];
      while (i < lines.length && /^\s*[-*]\s+/.test(lines[i])) {
        items.push(lines[i].replace(/^\s*[-*]\s+/, "").trim());
        i++;
      }
      blocks.push({ type: "bullets", items });
      continue;
    }

    // paragraph (collect consecutive non-blank lines that aren't special)
    const pLines = [];
    while (i < lines.length && lines[i].trim() !== "" &&
      !/^#{1,6}\s/.test(lines[i]) &&
      !lines[i].trim().startsWith("```") &&
      !/^---+\s*$/.test(lines[i].trim()) &&
      !/^\s*[-*]\s+/.test(lines[i]) &&
      !(lines[i].includes("|") && i + 1 < lines.length && /^\|[\s\-:|]+\|/.test((lines[i + 1] || "").trim()))
    ) {
      pLines.push(lines[i]);
      i++;
    }
    if (pLines.length > 0) {
      blocks.push({ type: "paragraph", text: pLines.join(" ") });
    }
  }

  return blocks;
}

// ── Inline formatting: parse **bold** ──

function parseInline(text) {
  const runs = [];
  const regex = /\*\*(.*?)\*\*/g;
  let last = 0;
  let m;
  while ((m = regex.exec(text)) !== null) {
    if (m.index > last) {
      runs.push(new TextRun({ text: text.slice(last, m.index), font: "Arial", size: 22 }));
    }
    runs.push(new TextRun({ text: m[1], font: "Arial", size: 22, bold: true }));
    last = m.index + m[0].length;
  }
  if (last < text.length) {
    runs.push(new TextRun({ text: text.slice(last), font: "Arial", size: 22 }));
  }
  return runs;
}

function parseInlineForTable(text) {
  const runs = [];
  const regex = /\*\*(.*?)\*\*/g;
  let last = 0;
  let m;
  while ((m = regex.exec(text)) !== null) {
    if (m.index > last) {
      runs.push(new TextRun({ text: text.slice(last, m.index), font: "Arial", size: 20 }));
    }
    runs.push(new TextRun({ text: m[1], font: "Arial", size: 20, bold: true }));
    last = m.index + m[0].length;
  }
  if (last < text.length) {
    runs.push(new TextRun({ text: text.slice(last), font: "Arial", size: 20 }));
  }
  return runs;
}

// ── Build docx children from blocks ──

function buildChildren(blocks, docTitle) {
  const children = [];
  let h1Count = 0;

  for (const block of blocks) {
    switch (block.type) {
      case "heading": {
        const isH1 = block.level === 1;
        if (isH1) h1Count++;

        const headingChildren = [];
        // Page break before H1 (except the first)
        if (isH1 && h1Count > 1) {
          headingChildren.push(new TextRun({ break: 1 })); // this doesn't actually do page break
        }

        const fontSize = block.level === 1 ? 32 : block.level === 2 ? 28 : 24; // half-points
        const headingLevel = block.level === 1 ? HeadingLevel.HEADING_1 :
          block.level === 2 ? HeadingLevel.HEADING_2 : HeadingLevel.HEADING_3;

        // For page break before H1 (except first), add a separate paragraph
        if (isH1 && h1Count > 1) {
          children.push(new Paragraph({
            children: [],
            pageBreakBefore: true,
          }));
        }

        children.push(new Paragraph({
          heading: headingLevel,
          spacing: { before: 240, after: 120 },
          children: [
            new TextRun({
              text: block.text,
              font: "Arial",
              size: fontSize,
              bold: true,
              color: "1F3864",
            }),
          ],
        }));
        break;
      }

      case "paragraph": {
        children.push(new Paragraph({
          spacing: { before: 60, after: 60 },
          children: parseInline(block.text),
        }));
        break;
      }

      case "bullets": {
        for (const item of block.items) {
          children.push(new Paragraph({
            numbering: { reference: "bullet-list", level: 0 },
            spacing: { before: 40, after: 40 },
            children: parseInline(item),
          }));
        }
        break;
      }

      case "code": {
        const codeLines = block.content.split("\n");
        for (const codeLine of codeLines) {
          children.push(new Paragraph({
            spacing: { before: 0, after: 0, line: 260 },
            shading: { type: ShadingType.CLEAR, fill: "F2F2F2" },
            children: [
              new TextRun({
                text: codeLine || " ",
                font: "Courier New",
                size: 18, // 9pt
                color: "333333",
              }),
            ],
          }));
        }
        // Add a small spacer after code block
        children.push(new Paragraph({ spacing: { before: 60, after: 60 }, children: [] }));
        break;
      }

      case "table": {
        const numCols = block.rows[0].length;
        const colWidth = Math.floor(9000 / numCols);

        const tableRows = block.rows.map((row, rowIdx) => {
          const isHeader = rowIdx === 0;
          const cells = [];
          for (let c = 0; c < numCols; c++) {
            const cellText = row[c] || "";
            cells.push(new TableCell({
              width: { size: colWidth, type: WidthType.DXA },
              shading: isHeader ? { type: ShadingType.CLEAR, fill: "D5E8F0" } : undefined,
              borders: {
                top: { style: BorderStyle.SINGLE, size: 1, color: "CCCCCC" },
                bottom: { style: BorderStyle.SINGLE, size: 1, color: "CCCCCC" },
                left: { style: BorderStyle.SINGLE, size: 1, color: "CCCCCC" },
                right: { style: BorderStyle.SINGLE, size: 1, color: "CCCCCC" },
              },
              children: [
                new Paragraph({
                  spacing: { before: 40, after: 40 },
                  children: isHeader
                    ? [new TextRun({ text: cellText, font: "Arial", size: 20, bold: true })]
                    : parseInlineForTable(cellText),
                }),
              ],
            }));
          }
          return new TableRow({ children: cells });
        });

        children.push(new Table({
          rows: tableRows,
          width: { size: 9000, type: WidthType.DXA },
        }));

        // spacer after table
        children.push(new Paragraph({ spacing: { before: 60, after: 60 }, children: [] }));
        break;
      }
    }
  }
  return children;
}

// ── Create document ──

function createDoc(blocks, title) {
  const bodyChildren = [];

  // Table of Contents
  bodyChildren.push(new Paragraph({
    heading: HeadingLevel.HEADING_1,
    spacing: { before: 0, after: 200 },
    children: [
      new TextRun({ text: "目录", font: "Arial", size: 32, bold: true, color: "1F3864" }),
    ],
  }));

  bodyChildren.push(new TableOfContents("目录", {
    hyperlink: true,
    headingStyleRange: "1-3",
  }));

  // Page break after TOC
  bodyChildren.push(new Paragraph({ children: [], pageBreakBefore: true }));

  // Main content
  bodyChildren.push(...buildChildren(blocks, title));

  const doc = new Document({
    styles: {
      default: {
        document: {
          run: { font: "Arial", size: 22 },
        },
        heading1: {
          run: { font: "Arial", size: 32, bold: true, color: "1F3864" },
        },
        heading2: {
          run: { font: "Arial", size: 28, bold: true, color: "1F3864" },
        },
        heading3: {
          run: { font: "Arial", size: 24, bold: true, color: "2E5090" },
        },
      },
    },
    numbering: {
      config: [
        {
          reference: "bullet-list",
          levels: [
            {
              level: 0,
              format: LevelFormat.BULLET,
              text: "\u2022",
              alignment: AlignmentType.LEFT,
              style: {
                paragraph: {
                  indent: { left: convertInchesToTwip(0.5), hanging: convertInchesToTwip(0.25) },
                },
              },
            },
          ],
        },
      ],
    },
    features: {
      updateFields: true,
    },
    sections: [
      {
        properties: {
          page: {
            size: { width: 11906, height: 16838 }, // A4
            margin: {
              top: convertInchesToTwip(1),
              bottom: convertInchesToTwip(1),
              left: convertInchesToTwip(1),
              right: convertInchesToTwip(1),
            },
          },
        },
        headers: {
          default: new Header({
            children: [
              new Paragraph({
                alignment: AlignmentType.RIGHT,
                spacing: { after: 100 },
                border: {
                  bottom: { style: BorderStyle.SINGLE, size: 1, color: "CCCCCC", space: 4 },
                },
                children: [
                  new TextRun({
                    text: title,
                    font: "Arial",
                    size: 18,
                    color: "888888",
                    italics: true,
                  }),
                ],
              }),
            ],
          }),
        },
        footers: {
          default: new Footer({
            children: [
              new Paragraph({
                alignment: AlignmentType.CENTER,
                border: {
                  top: { style: BorderStyle.SINGLE, size: 1, color: "CCCCCC", space: 4 },
                },
                children: [
                  new TextRun({
                    children: [PageNumber.CURRENT],
                    font: "Arial",
                    size: 18,
                    color: "888888",
                  }),
                  new TextRun({
                    text: " / ",
                    font: "Arial",
                    size: 18,
                    color: "888888",
                  }),
                  new TextRun({
                    children: [PageNumber.TOTAL_PAGES],
                    font: "Arial",
                    size: 18,
                    color: "888888",
                  }),
                ],
              }),
            ],
          }),
        },
        children: bodyChildren,
      },
    ],
  });

  return doc;
}

// ── Table cell text with inline parsing for table bodies ──
// Fix the table cell rendering to properly handle inline formatting

function buildTableChildren(blocks, docTitle) {
  // Already handled inside buildChildren - this is a placeholder
}

// ── Main ──

async function generate(mdPath, outPath, title) {
  const md = fs.readFileSync(mdPath, "utf-8");
  const blocks = parseMd(md);
  const doc = createDoc(blocks, title);
  const buffer = await Packer.toBuffer(doc);
  fs.writeFileSync(outPath, buffer);
  console.log(`Generated: ${outPath} (${buffer.length} bytes)`);
}

async function main() {
  const dir = "/home/chu2026/Documents/APQPOS/doc/plans";

  await generate(
    path.join(dir, "2026-03-18-technical-proposal.md"),
    path.join(dir, "APQP-OS技术方案.docx"),
    "APQP-OS 技术方案"
  );

  await generate(
    path.join(dir, "2026-03-18-technical-overview.md"),
    path.join(dir, "APQP-OS技术概览.docx"),
    "APQP-OS 技术概览"
  );
}

main().catch(e => { console.error(e); process.exit(1); });
