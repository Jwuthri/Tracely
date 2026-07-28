# GSAP Timeline

## Creation

```js
const tl = gsap.timeline({
  defaults: { duration: 0.8, ease: "power2.out" }, // applique a tous les enfants
  paused: false,
  repeat: -1,           // -1 = infini
  yoyo: true,
  repeatDelay: 0.5,
  onComplete: () => console.log("done"),
});
```

## Position Parameter

Le parametre de position controle OU un tween est insere dans le timeline. C'est le 3eme argument de `.to()`, `.from()`, `.fromTo()`, `.add()`.

### Valeurs absolues

```js
tl.to(".a", { x: 100 }, 0);     // a exactement 0s (debut du timeline)
tl.to(".b", { x: 100 }, 1);     // a exactement 1s
tl.to(".c", { x: 100 }, 2.5);   // a exactement 2.5s
```

### Relatif a la fin du timeline

```js
tl.to(".a", { x: 100 });              // s'ajoute a la fin
tl.to(".b", { x: 100 }, "+=0.5");     // 0.5s APRES la fin
tl.to(".c", { x: 100 }, "-=0.3");     // 0.3s AVANT la fin (overlap)
```

### Relatif au tween precedent

```js
tl.to(".a", { x: 100 });
tl.to(".b", { x: 100 }, "<");         // meme debut que le precedent
tl.to(".c", { x: 100 }, "<0.2");      // 0.2s apres le DEBUT du precedent
tl.to(".d", { x: 100 }, ">");         // a la FIN du precedent
tl.to(".e", { x: 100 }, ">-0.1");     // 0.1s AVANT la fin du precedent
```

### Avec labels

```js
tl.addLabel("intro", 1);
tl.to(".a", { x: 100 }, "intro");       // au label
tl.to(".b", { x: 100 }, "intro+=0.3");  // 0.3s apres le label
```

## Cheatsheet position

```
tl ─────────────────────────────────────>
   |  A  |      |  B  |
              |  C  |       |  D  |
                         |  E  |

A: tl.to(a, {}, 0)          // absolue
B: tl.to(b, {})             // sequentiel (fin de A)
C: tl.to(c, {}, "<")        // debut de B
D: tl.to(d, {}, "+=0.5")    // 0.5s apres fin de C
E: tl.to(e, {}, ">-0.2")    // 0.2s avant fin de D
```

## Labels

```js
tl.addLabel("reveal", "+=0.5");      // ajoute un label a la position courante + 0.5s
tl.to(".box", { x: 200 }, "reveal"); // utilise le label comme position

tl.play("reveal");                   // joue depuis le label
tl.seek("reveal");                   // saute au label sans jouer
```

## Methode .add()

Ajoute des tweens, callbacks, ou labels.

```js
tl.add(gsap.to(".a", { x: 100 }), 1);           // tween a 1s
tl.add(() => console.log("checkpoint"), "+=0.5"); // callback
tl.add("myLabel");                                 // raccourci label
```

## Nesting (timelines imbriques)

Les timelines peuvent contenir d'autres timelines. Chaque sous-timeline agit comme un seul "bloc" dans le parent.

```js
function heroAnimation() {
  const tl = gsap.timeline();
  tl.from(".hero-title", { y: 50, opacity: 0 })
    .from(".hero-subtitle", { y: 30, opacity: 0 }, "<0.2")
    .from(".hero-cta", { scale: 0.8, opacity: 0 }, "<0.1");
  return tl;
}

function cardsAnimation() {
  const tl = gsap.timeline();
  tl.from(".card", { y: 40, opacity: 0, stagger: 0.15 });
  return tl;
}

// Timeline maitre
const master = gsap.timeline();
master
  .add(heroAnimation())
  .add(cardsAnimation(), "-=0.3"); // overlap de 0.3s
```

**Avantage** : chaque section est encapsulee, testable, et repositionnable.

## defaults sur Timeline

Les defaults se propagent aux enfants directs mais PAS aux timelines imbriques.

```js
const tl = gsap.timeline({
  defaults: { duration: 1, ease: "power3.out" },
});

tl.to(".a", { x: 100 });           // duration: 1, ease: power3.out
tl.to(".b", { x: 100, duration: 2 }); // duration: 2 (override), ease: power3.out

// Timeline enfant : ses propres defaults s'appliquent
const child = gsap.timeline({ defaults: { duration: 0.5 } });
tl.add(child); // les defaults du parent NE s'appliquent PAS aux tweens de child
```

## Controle du Timeline

```js
tl.play();
tl.pause();
tl.resume();
tl.reverse();
tl.restart();
tl.kill();

// Navigation
tl.seek(2);              // saute a 2s
tl.seek("myLabel");      // saute au label
tl.progress(0.5);        // saute a 50%
tl.time(1.5);            // saute a 1.5s

// Vitesse
tl.timeScale(2);         // 2x plus rapide
tl.timeScale(0.5);       // 2x plus lent

// Etat
tl.isActive();           // en cours de lecture ?
tl.totalDuration();      // duree totale incluant repeats
tl.paused();             // en pause ?

// Modification
tl.clear();              // vide le timeline (garde l'instance)
tl.invalidate();         // reset les valeurs de depart
tl.totalProgress(0);     // remet au debut
```

## Patterns courants

### Timeline responsive avec matchMedia

```js
ScrollTrigger.matchMedia({
  "(min-width: 768px)": function () {
    // animations desktop
    gsap.timeline({ scrollTrigger: { trigger: ".section" } })
      .to(".box", { x: 500 });
  },
  "(max-width: 767px)": function () {
    // animations mobile (plus simple)
    gsap.to(".box", { y: 100, scrollTrigger: ".section" });
  },
});
// Cleanup automatique quand le media query ne matche plus
```

### Timeline avec ScrollTrigger

```js
const tl = gsap.timeline({
  scrollTrigger: {
    trigger: ".section",
    start: "top center",
    end: "bottom center",
    scrub: 1,
    // NE PAS mettre de ScrollTrigger sur les enfants du timeline
  },
});

tl.to(".a", { x: 200 })
  .to(".b", { rotation: 360 }, "<")
  .to(".c", { scale: 2 }, "+=0.3");
```

### Kill proprement en React

```jsx
import { useGSAP } from "@gsap/react";

function Component() {
  const container = useRef();

  useGSAP(() => {
    const tl = gsap.timeline();
    tl.to(".box", { x: 200 });
    // cleanup automatique par useGSAP
  }, { scope: container });

  return <div ref={container}>...</div>;
}
```
