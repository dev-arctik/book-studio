// manual/pipeline/book_template.typ
// Typst layout for the clean book PDF: title page, contents, front sections (Foreword, Introduction), then chapters.
// Chapters hold prose blocks (paragraphs, verse quotes, sources, signatures) and/or verses (Sanskrit, word-for-word, translation, poet).
// Reads its content from a JSON file passed in by typeset_book.py (sys.inputs.data), so no Sanskrit text is ever escaped into code.

#let data = json(sys.inputs.data)
#let meta = data.meta

#let accent = rgb("#7a4a12")
#let soft = rgb("#6b6158")

#set document(title: meta.title, author: meta.author)
#set text(font: "Gentium Book Plus", size: 11pt, lang: "en", hyphenate: true)
#set par(justify: true, leading: 0.62em, spacing: 0.9em)

// Rich text arrives as segments [{t, i, b}] — italics/bold kept from the scan
#let rich(segs) = segs.map(s => {
  let t = if s.i and s.b { strong(emph(s.t)) } else if s.i { emph(s.t) } else if s.b { strong(s.t) } else { s.t }
  // Footnote markers and ordinals ("day.¹", "10th") stay raised, as printed
  if s.at("sup", default: false) { super(t) } else { t }
}).join()

// Drawn as shapes rather than a ✦ character, which Gentium doesn't have (it would fall back to a math font)
#let diamond(size) = box(rotate(45deg, square(size: size, fill: accent)))
#let ornament = align(center, stack(dir: ltr, spacing: 7pt, diamond(2.6pt), diamond(3.6pt), diamond(2.6pt)))

#set page(
  width: 148mm, height: 210mm, // A5: close to the original's trim size and easy to print
  margin: (x: 18mm, top: 22mm, bottom: 20mm),
  header: context {
    // No running header on pages where a chapter opens — the big title already says where you are
    let opens = query(heading.where(level: 1)).filter(h => h.location().page() == here().page())
    if opens.len() == 0 and counter(page).get().first() > 0 {
      align(center, text(size: 8.5pt, fill: soft, tracking: 0.05em, smallcaps(meta.title)))
    }
  },
  footer: context {
    if counter(page).get().first() > 0 { align(center, text(size: 9pt, fill: soft, counter(page).display())) }
  },
)

#let verse(vs) = {  // not 'v' — that would shadow Typst's v() spacing function
  // Keep the verse heading and its Sanskrit together; the rest may flow onto the next page
  // width: 100% — without it the block shrinks to its text and the "centred" Sanskrit hugs the left margin
  block(width: 100%, breakable: false, above: 1.8em, below: 0.9em)[
    #align(center, text(fill: accent, size: 9.5pt, tracking: 0.12em, smallcaps[Verse #vs.number]))
    #v(0.3em)
    #align(center, text(style: "italic", size: 11pt, vs.sanskrit.map(l => [#l]).join(linebreak())))
  ]
  if vs.word_for_word.len() > 0 {
    block(above: 0.9em, text(size: 9.5pt, rich(vs.word_for_word)))
  }
  for tr in vs.translations {
    if tr.label != none { block(above: 0.9em, below: 0.4em, text(size: 9.5pt, fill: accent, smallcaps(tr.label))) }
    for p in tr.paragraphs { block(above: 0.7em, rich(p)) }
  }
  if vs.poet != "" { align(right, block(above: 0.6em, text(style: "italic", fill: soft)[— #vs.poet])) }
  for n in vs.notes { block(above: 0.7em, text(size: 10pt, rich(n))) }
}

// One prose block. Verse-anthology paragraphs keep their spaced look; prose books read like a novel (indented, tighter).
#let prose-block(b) = {
  if b.type == "p" {
    if data.layout == "prose" {
      // A little more line spacing than the verse books: full pages of story text are tiring for young readers
      block(above: 0.55em, below: 0.55em, { set par(leading: 0.78em); if b.indent { h(1.3em) }; rich(b.segs) })
    } else { block(rich(b.segs)) }
  } else if b.type == "quote" {
    // Sanskrit verse quoted in the text: centred italic lines, set apart from the story
    block(width: 100%, breakable: false, above: 1em, below: 0.4em,
      align(center, text(style: "italic", b.lines.map(l => [#l]).join(linebreak()))))
  } else if b.type == "epigraph" {
    block(width: 100%, inset: (x: 1.5em), above: 0.8em, below: 0.3em, text(size: 10pt, style: "italic", rich(b.segs)))
  } else if b.type == "blockquote" {
    // A quoted prose passage, set in from both margins and a little smaller, as in the printed book
    block(width: 100%, inset: (x: 1.5em), above: 0.9em, below: 0.9em, text(size: 10pt, rich(b.segs)))
  } else if b.type == "cite" {
    block(width: 100%, above: 0.3em, below: 0.9em, align(right, text(size: 9pt, fill: soft, rich(b.segs))))
  } else if b.type == "sign" {
    block(width: 100%, above: 0.9em, below: 0.2em, align(right, text(style: "italic")[— #rich(b.segs)]))
  } else if b.type == "sign-detail" {
    align(right, text(size: 9pt, fill: soft, rich(b.segs)))
  } else if b.type == "figure" {
    // Size from the picture's shape: tall Deity photos capped by height, wide temple drawings by width
    block(width: 100%, breakable: false, above: 1.3em, below: 1.3em, align(center, {
      image(b.path, width: calc.min(100mm, 92mm / b.aspect))
      if b.caption.len() > 0 {
        v(0.45em)
        block(width: 85%, text(size: 9pt, style: "italic", fill: soft, rich(b.caption)))
      }
    }))
  } else if b.type == "h" {
    block(above: 1.3em, below: 0.6em, sticky: true, text(fill: accent, size: 10.5pt, weight: "bold", rich(b.segs)))
  } else if b.type == "break" {
    // Scene break ("* * * *" in the original)
    block(width: 100%, above: 1em, below: 1em, align(center, text(fill: accent, tracking: 0.6em)[\* \* \*]))
  } else if b.type == "centred" {
    // Centred lines kept as printed (a boxed list: "11 / Family Love and Affection")
    block(width: 100%, above: 0.9em, below: 0.9em, align(center, b.lines.map(l => rich(l)).join(linebreak())))
  } else if b.type == "table" {
    // A table from the book; a row with a single filled cell is the table's own title ("Empathic Listening Categories")
    let n = b.rows.at(0).len()
    let cells = ()
    for row in b.rows {
      let filled = row.filter(c => c.len() > 0)
      if filled.len() == 1 and n > 1 and row.at(0).len() == 0 {
        cells.push(table.cell(colspan: n, align: center, text(fill: accent, weight: "bold", rich(filled.at(0)))))
      } else {
        for c in row { cells.push(if c.len() == 0 [] else { rich(c) }) }
      }
    }
    block(width: 100%, above: 1em, below: 1em, text(size: 9pt, table(
      columns: n, stroke: 0.4pt + soft, inset: (x: 5pt, y: 4pt), align: left + top, ..cells)))
  } else if b.type == "notes-h" {
    block(width: 100%, above: 2em, below: 0.7em, sticky: true, {
      line(length: 30%, stroke: 0.5pt + soft)
      v(0.3em)
      text(size: 9pt, fill: accent, tracking: 0.1em, smallcaps[Notes])
    })
  } else if b.type == "entry" {
    // List entries such as a bibliography: hanging indent, so each entry's first word stands out
    block(above: 0.45em, below: 0.45em, par(hanging-indent: 1.5em, text(size: 10pt, rich(b.segs))))
  } else if b.type == "note" {
    // Endnotes in small print; the number is part of the text ("3. Cc. Ādi-līlā 8.73, Purport.")
    block(above: 0.35em, below: 0.35em, text(size: 8.5pt, fill: soft, rich(b.segs)))
  }
}

// A Part opens on its own page: "PART ONE" above the part's name, nothing else on the page
#let part-page(ch, i) = {
  pagebreak(weak: true)
  // The book's own full-page painting already carries "PART ONE · Kusuma-sarovara"; the heading stays (hidden) for contents links
  if ch.at("cover", default: none) != none {
    [#hide(heading(level: 1, outlined: true, ch.title)) #label("ch-" + str(i))]
    v(1fr)
    align(center, image(ch.cover.path, height: 160mm))
    v(1fr)
    return
  }
  // A Part page may print its painting under the title (Saṅkalpa-kaumudī): then the title sits higher to leave room
  let paintings = ch.blocks.filter(b => b.type == "figure")
  v(if paintings.len() > 0 { 12mm } else { 55mm })
  align(center)[
    #text(size: 10pt, fill: soft, tracking: 0.25em, upper(ch.subtitle))
    #v(0.8em)
    #heading(level: 1, outlined: true, text(size: 24pt, style: "italic", fill: accent, weight: "regular", ch.title)) #label("ch-" + str(i))
    #v(1em)
    #ornament
  ]
  for b in paintings { prose-block(b) }
}

#let chapter(ch, i) = {
  if ch.at("part", default: false) { return part-page(ch, i) }
  pagebreak(weak: true)
  v(14mm)
  align(center)[
    // Closing sections like "A Few Words…" carry no chapter number
    #if ch.number != none [#text(size: 9pt, fill: soft, tracking: 0.15em)[CHAPTER #ch.number] \ #v(0.6em)]
    #heading(level: 1, outlined: true, text(size: 19pt, style: "italic", fill: accent, weight: "regular", ch.title)) #label("ch-" + str(i))
    #v(0.2em)
    #text(size: 12pt, fill: soft, ch.subtitle)
  ]
  v(0.4em)
  ornament
  v(0.6em)
  for b in ch.blocks { prose-block(b) }
  for vs in ch.verses { verse(vs) }
}

// ---------- Front matter ----------
// Wrapped in a code block so its header/footer/text-size set rules don't leak into the chapters
#{
  // The original front cover, full-bleed on a page with the cover's own proportions
  if data.at("cover", default: none) != none {
    page(width: 148mm, height: 148mm * data.cover.aspect, margin: 0pt, header: none, footer: none,
      image(data.cover.path, width: 100%, height: 100%))
  }
  set page(header: none, footer: none)
  counter(page).update(0)
  v(40mm)
  align(center)[
    #text(size: 30pt, style: "italic", fill: accent, meta.title)
    #v(0.4em)
    #text(size: 13pt, fill: soft, meta.subtitle)
    #v(2.5em)
    #ornament
    #v(2.5em)
    #text(size: 15pt, meta.author)
    #v(1fr)
    #for c in meta.credits [#text(size: 10pt, fill: soft, c) \ ]
    // Opt-in copyright line (Book Studio's toggle); the approved design has none, so finished books are unchanged
    #if meta.at("copyright", default: "") != "" [#v(0.5em) #text(size: 8.5pt, fill: soft, meta.copyright)]
  ]

  // Frontispiece: the original's dedication portrait or Deity photos from its front pages, each on its own page
  for fig in data.at("frontispiece", default: ()) {
    pagebreak()
    v(1fr)
    align(center, image(fig.path, width: calc.min(100mm, 150mm / fig.aspect)))
    v(1fr)
  }

  pagebreak()
  counter(page).update(1)
  set page(header: none, footer: context align(center, text(size: 9pt, fill: soft, counter(page).display("i"))))
  align(center, text(size: 16pt, style: "italic", fill: accent)[Contents])
  v(1em)
  set text(size: 10pt)
  for (i, ch) in data.chapters.enumerate() {
    context {
      let loc = locate(label("ch-" + str(i)))
      block(below: 0.75em, link(loc, grid(
        columns: (2em, 1fr, auto), column-gutter: 0.6em,
        text(fill: soft)[#if ch.number != none [#ch.number.]],
        // Part rows stand out as group titles; chapters list title and subtitle
        if ch.at("part", default: false) { text(fill: accent, weight: "bold")[#ch.subtitle: #ch.title] }
        else [#emph(ch.title) #if ch.subtitle != "" { text(fill: soft, size: 9pt)[— #ch.subtitle] }],
        str(counter(page).at(loc).first()),
      )))
    }
  }

  // Foreword, Introduction… — unnumbered, on roman-numbered pages before chapter 1
  for sec in data.front {
    pagebreak()
    align(center, text(size: 16pt, style: "italic", fill: accent, sec.title))
    v(1em)
    for b in sec.blocks { prose-block(b) }
  }

  pagebreak()
  counter(page).update(1)
}

// ---------- Chapters ----------
#for (i, ch) in data.chapters.enumerate() { chapter(ch, i) }
