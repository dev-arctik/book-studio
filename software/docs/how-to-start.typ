// software/docs/how-to-start.typ
// The one-page "HOW TO START" guide that ships inside BookStudio-<version>.zip, for volunteers who are not technical.
// build_zip.py compiles it to "HOW TO START.pdf" with the bundled Gentium font, in the books' own colours.

#let accent = rgb("#7a4a12")
#let soft = rgb("#6b6158")
#set document(title: "How to start Book Studio")
#set page(paper: "a4", margin: (x: 20mm, y: 16mm))
#set text(font: "Gentium Book Plus", size: 10.5pt)
#set par(leading: 0.55em, spacing: 0.75em)
#show heading.where(level: 2): it => block(above: 1.1em, below: 0.5em, text(fill: accent, size: 13pt, weight: "bold", it.body))
#let step(n, body) = grid(columns: (7mm, 1fr), column-gutter: 2mm, align: top,
  move(dy: -1.2pt, box(fill: accent, radius: 50%, width: 5.4mm, height: 5.4mm, align(center + horizon, text(fill: white, weight: "bold", size: 9pt, str(n))))),
  body)
#let note(body) = block(fill: rgb("#f3e9dc"), inset: 8pt, radius: 5pt, width: 100%, text(size: 9.5pt, body))

#align(center)[
  #text(size: 24pt, style: "italic", fill: accent)[Book Studio] \
  #text(fill: soft)[Turns scanned books into clean PDFs and e-books — on your own computer]
]

== The first time (about 10 minutes, needs internet once)

#step(1)[*Unzip* the file you received (double-click it). Move the *BookStudio* folder somewhere it can stay — for example Documents. Don't delete it later: Book Studio lives in it.]
#step(2)[Open the BookStudio folder and *double-click the Start file* for your computer:]
#table(columns: (auto, 1fr), stroke: 0.4pt + soft, inset: 6pt,
  [*Mac*], [*Start Book Studio.command* — the first time, macOS says it "cannot be opened because it is from an unidentified developer". Click *Done*, then *right-click* the file → *Open* → *Open*. Only once.],
  [*Windows*], [*Start Book Studio.bat* — if a blue box says "Windows protected your PC", click *More info* → *Run anyway*. Only once.],
  [*Linux*], [*start-book-studio.sh* — right-click → *Run as a Program* (or open a terminal in the folder and type `sh start-book-studio.sh`). On Ubuntu, if the window doesn't open: `sudo apt install libxcb-cursor0`.],
)
#step(3)[A window shows the setup steps. *Leave it open* until Book Studio itself opens.]
#step(4)[Book Studio asks for two things: the *page reader* (downloads by itself) and the *reading model* (1.4 GB): click *Download it* — or *Load from a folder* if someone gave you a USB stick with the model. Keep *"Put a Book Studio icon on the Desktop"* ticked and click *Start using Book Studio*.]

== Every day after that

Double-click the *Book Studio* icon on your Desktop. No internet needed.

#step(1)[*+ Add books* — choose the scanned PDFs (or drag them onto the window). Each book appears as its cover.]
#step(2)[Click a book to check its *title, subtitle and author*. *Choose image…* sets your own cover photo; *Copyright line* adds one to the title page.]
#step(3)[*Make books* — Book Studio reads every page, then makes the PDF and the e-book (EPUB). A big book takes many hours; the bar at the bottom says how long is left.]
#step(4)[*Open finished books* — your PDFs and EPUBs are there.]

#note[*Cooling down.* While reading pages the computer works hard. By default Book Studio works 60 minutes, then rests 15, and rests an hour between books (change it in *Settings*). *Pause*, *Stop* or even closing Book Studio loses nothing — pages already read are kept, and *Make books* continues where it stopped. Keep a laptop plugged in.]

== If something goes wrong

- A book shows *Needs attention*: click it → *Warnings*. It shows what Book Studio found next to the scanned page. Send that book to Devansh if it isn't clear.
- *Changed* means you edited the book after it was made — click *Make books* again; it takes seconds.
- *Updates* come by themselves: when Book Studio offers one, click *Update now*. Your books and settings are kept.

#align(center, text(size: 9pt, fill: soft)[Your books never leave your computer. Book Studio only goes online to download itself, the reading model and updates.])
