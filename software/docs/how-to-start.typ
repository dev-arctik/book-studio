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
#note[*The Start file opens as text instead* (in VS Code, TextEdit or another editor)? Your computer sends script files to that editor. Start it this way instead:
- *Mac:* right-click *Start Book Studio.command* → *Open With* → *Terminal* (not listed? *Other…* → Applications → Utilities → Terminal). Or open *Terminal*, type `sh` and a space, drag the file into the window and press Enter.
- *Windows:* right-click *Start Book Studio.bat* → *Open* (not *Edit*).
- *Linux:* open a terminal in the BookStudio folder and type `sh start-book-studio.sh`.
You need this only the first time — afterwards the Book Studio icon on the Desktop opens it.]
#step(3)[A window shows the setup steps. *Leave it open* until Book Studio itself opens.]
#step(4)[Book Studio asks for two things: the *page reader* (downloads by itself) and the *reading model* (1.4 GB): click *Download it* — or *Load from a folder* if someone gave you a USB stick with the model. Keep *"Put a Book Studio icon on the Desktop"* ticked and click *Start using Book Studio*.]

== Every day after that

Double-click the *Book Studio* icon on your Desktop. No internet needed.

#step(1)[*+ Add books* — choose PDF files or a whole folder (or drag them onto the window). Each book gets its own row.]
#step(2)[*Tick* the books to make (*Select all* ticks every one). Click a book's row to check its *title, subtitle and author*, choose your own cover photo, or untick *Keep the book's copyright page*.]
#step(3)[*Make ticked books* — each book goes through *Read → Chapters → PDF → EPUB*; its row shows where it is, with pages done and time left, and the card at the top shows the whole run. A big book takes many hours.]
#step(4)[*Open finished books* — the PDFs are in the *PDF* folder, the e-books in the *EPUB* folder.]

#note[*Cooling down.* While reading pages the computer works hard. By default Book Studio works 60 minutes, then rests 15, and rests an hour between books (change it in *Settings*). *Pause*, *Stop*, closing Book Studio — even the computer turning off — loses nothing — pages already read are kept, and *Make ticked books* continues where it stopped. Keep a laptop *plugged in* and its *lid open*: Book Studio keeps the computer awake while it works, and if the battery drops below 15 % it pauses by itself until the charger is plugged in.]

== If something goes wrong

- After a book is made, open its *⋯* menu → *Check book*: it says whether every chapter was found and lists pages worth a look, beside the scanned page. A book showing *Needs attention* explains what went wrong there too — send that book to Devansh if it isn't clear.
- *Changed* means you edited the book after it was made — press *Make ticked books* again; it takes seconds.
- *Updates* come by themselves: when Book Studio offers one, click *Update now*. Your books and settings are kept.

#align(center, text(size: 9pt, fill: soft)[Your books never leave your computer. Book Studio only goes online to download itself, the reading model and updates.])
