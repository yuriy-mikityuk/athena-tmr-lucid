# Guide pictures

The meditation guide (`/guide.html`) folds one infographic under its intro, one file
per language:

- `src/muse_tmr/app/static/guide-why-en.webp`
- `src/muse_tmr/app/static/guide-why-ru.webp`

Both are 1536 x 1024 WebP, about 220 KB each. The page text already says everything
the picture says (sections 02 and 05), so the picture is a shortcut, not the only
copy of anything. Keep it that way: the text is what is searched, translated and
read aloud.

The pictures are generated, so a wording change means generating again. Rules that
keep them consistent with the page:

- Practice A is the focus practice, in the page's teal (`#0f766e`); practice B is open
  awareness, in the page's orange (`#b45309`). Letters are fine inside the picture
  because cards 1 and 2 define them.
- The card texts below are the source. The picture must carry them exactly, and the
  practice names must match what the voice says: "Focus on the breath" and "Open
  awareness"; «Фокус на дыхании» and «Открытое внимание».
- Proofread every card before replacing a file: generators drop and double letters.
- Each language is generated from its own prompt below; the two prompts say the same
  thing. Attaching the other language's picture as a reference tends to copy whatever
  file was attached, so check that it is the current one before doing that.

Replace the file in place and open the page: the `<img>` has fixed width and height
attributes, so a new file of the same shape needs no HTML change.

## Prompt (Russian)

```text
Создай обучающую инфографику: горизонтальный формат 3:2, плоская чистая иллюстрация в стиле современной журнальной инфографики, не детская. Фон светлый тёплый (почти белый, #faf8f4), текст тёмно-синий (#1b232d), жирный округлый шрифт в заголовках, без цветной плашки под заголовком. 6 карточек со скруглёнными углами в 2 ряда по 3, у каждой номер в кружке слева от заголовка, фоны карточек светлые, чуть разных оттенков. В каждой карточке рисунок крупный, одной высоты во всех карточках, в скруглённой рамке, подпись под ним. Персонаж один и тот же во всех карточках: спокойный взрослый человек в тонком обруче с датчиками, нарисован просто, без мультяшных глаз.

Практика А везде бирюзовый (сине-зелёный, #0f766e) квадратик с белой буквой «А», практика Б везде тёплый оранжевый (#b45309) квадратик с белой буквой «Б». Текст только на русском, ровно как в кавычках, без опечаток и без добавленных слов. Другого текста на картинке нет.

Сверху заголовок «Две практики и зачем их чередовать», под ним строка помельче «Полчаса, четыре блока по 8 минут, голос называет каждый».

Карточка 1. Справа от заголовка бирюзовый квадратик «А». Заголовок «А: фокус на дыхании»
Текст: «Выбери одно место, где дыхание чувствуется лучше всего, и держи внимание там. Ушёл в мысли, заметил, вернулся.»
Картинка: человек сидит с закрытыми глазами, узкий луч света освещает одну точку у носа. Подпись: «Как луч фонарика на одной точке».

Карточка 2. Справа от заголовка оранжевый квадратик «Б». Заголовок «Б: открытое внимание»
Текст: «Ни за что не держись. Замечай всё, что появляется: звуки, тело, дыхание, мысли. Пусть приходит и уходит само.»
Картинка: тот же человек, над ним лампа, мягкий свет на всю комнату, в свете маленькие значки: нотка, волна, облачко мысли. Подпись: «Как лампа на всю комнату».

Карточка 3. Заголовок «Что мешает сравнить»
Текст: «За полчаса всё медленно плывёт: тело расслабляется, клонит в сон. Запись меняется сама, без всякой практики.»
Картинка: лента времени от «0» до «30 мин», над ней три лица по порядку: бодрое, зевающее, дремлющее. Под лентой плавная линия вниз, подпись «Запись меняется сама».

Карточка 4. Заголовок «Если А всегда раньше»
Текст: «А достаются бодрые минуты, Б сонные. Разница между практиками и сонливость слились в одно, их не разделить.»
Картинка: лента с квадратиками «А» «А» «Б» «Б», под ней та же линия вниз. Весы наклонены в сторону «А», над ними вопросительный знак.

Карточка 5. Заголовок «Поэтому А Б Б А»
Текст: «У каждой практики один ранний блок и один поздний. Сонливость вычитается, остаётся разница между практиками. На середине голос говорит: снова.»
Картинка: лента с квадратиками «А» «Б» «Б» «А», посередине пунктирная ось как зеркало. Весы ровно, над ними зелёная галочка.

Карточка 6. Заголовок «Одна сессия, одна точка»
Текст: «В одной сессии А Б Б А, в другой Б А А Б, первой бывает каждая. Чтобы отличить разницу от случайности, нужно хотя бы 8 сессий.»
Картинка: столбик из четырёх маленьких лент «А Б Б А», «Б А А Б», «А Б Б А», «Б А А Б», рядом календарь ровно с восемью галочками.
```

## Prompt (English)

```text
Create an educational infographic: landscape 3:2, flat clean illustration in the style of a modern magazine infographic, not childish. Light warm background (near white, #faf8f4), dark navy text (#1b232d), bold rounded font for headings. 6 cards with rounded corners in 2 rows of 3, each with its number in a circle next to the heading, card backgrounds light in slightly different tints. One character: a calm adult in a thin headband with small sensors, drawn simply, without cartoon eyes.

Practice A is always a teal (blue-green, #0f766e) square with a white letter "A", practice B is always a warm orange (#b45309) square with a white letter "B". Text in English only, exactly as quoted, with no typos and no added words. No other text in the picture.

At the top the title "Two practices and why we alternate them", below it a smaller line "Half an hour, four blocks of 8 minutes, the voice names each one".

Card 1. A teal square "A" in the corner. Heading "A: focus on the breath"
Text: "Choose one place where you feel the breath best, and keep your attention there. Lost in thoughts, noticed, came back."
Picture: the person sits with eyes closed, a narrow beam of light lights one point at the nose. Caption: "Like a flashlight beam on one point".

Card 2. An orange square "B" in the corner. Heading "B: open awareness"
Text: "Don't hold on to anything. Notice whatever appears: sounds, the body, the breath, thoughts. Let it come and go on its own."
Picture: the same person, a lamp above, soft light fills the whole room, small icons in the light: a music note, a wave, a thought cloud. Caption: "Like a lamp that lights the whole room".

Card 3. Heading "What makes comparing hard"
Text: "Over half an hour everything slowly drifts: the body relaxes, you get sleepy. The recording changes on its own, without any practice."
Picture: a timeline from "0" to "30 min", above it three small faces in order: alert, yawning, dozing. Below the timeline a smooth line going down, caption "The recording changes on its own".

Card 4. Heading "If A is always first"
Text: "A gets the alert minutes, B the sleepy ones. The difference between the practices and the sleepiness merge into one and cannot be separated."
Picture: a timeline with squares "A" "A" "B" "B", below it the same line going down. A balance scale tipped towards "A", a question mark above it.

Card 5. Heading "So the order is A B B A"
Text: "Each practice has one early block and one late block. Sleepiness cancels out, and only the difference between the practices is left. In the middle the voice says: again."
Picture: a timeline with squares "A" "B" "B" "A", a dashed axis of symmetry in the middle like a mirror. The scale is level, a green check mark above it.

Card 6. Heading "One session, one data point"
Text: "In one session A B B A, in another B A A B, and each one goes first sometimes. To tell a difference from chance, you need at least 8 sessions."
Picture: a column of four small timelines "A B B A", "B A A B", "A B B A", "B A A B", next to it a calendar with eight check marks.
```
