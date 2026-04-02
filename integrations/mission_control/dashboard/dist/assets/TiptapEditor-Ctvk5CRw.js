import{u as a,i as r,d as l,j as e,E as h}from"./tiptap-Bih96lpt.js";import{c as o}from"./index-C9jydQT5.js";/**
 * @license lucide-react v1.7.0 - ISC
 *
 * This source code is licensed under the ISC license.
 * See the LICENSE file in the root directory of this source tree.
 */const u=[["path",{d:"M6 12h9a4 4 0 0 1 0 8H7a1 1 0 0 1-1-1V5a1 1 0 0 1 1-1h7a4 4 0 0 1 0 8",key:"mg9rjx"}]],x=o("bold",u);/**
 * @license lucide-react v1.7.0 - ISC
 *
 * This source code is licensed under the ISC license.
 * See the LICENSE file in the root directory of this source tree.
 */const p=[["path",{d:"M4 12h8",key:"17cfdx"}],["path",{d:"M4 18V6",key:"1rz3zl"}],["path",{d:"M12 18V6",key:"zqpxq5"}],["path",{d:"M21 18h-4c0-4 4-3 4-6 0-1.5-2-2.5-4-1",key:"9jr5yi"}]],y=o("heading-2",p);/**
 * @license lucide-react v1.7.0 - ISC
 *
 * This source code is licensed under the ISC license.
 * See the LICENSE file in the root directory of this source tree.
 */const g=[["line",{x1:"19",x2:"10",y1:"4",y2:"4",key:"15jd3p"}],["line",{x1:"14",x2:"5",y1:"20",y2:"20",key:"bu0au3"}],["line",{x1:"15",x2:"9",y1:"4",y2:"20",key:"uljnxc"}]],k=o("italic",g);/**
 * @license lucide-react v1.7.0 - ISC
 *
 * This source code is licensed under the ISC license.
 * See the LICENSE file in the root directory of this source tree.
 */const f=[["path",{d:"M11 5h10",key:"1cz7ny"}],["path",{d:"M11 12h10",key:"1438ji"}],["path",{d:"M11 19h10",key:"11t30w"}],["path",{d:"M4 4h1v5",key:"10yrso"}],["path",{d:"M4 9h2",key:"r1h2o0"}],["path",{d:"M6.5 20H3.4c0-1 2.6-1.925 2.6-3.5a1.5 1.5 0 0 0-2.6-1.02",key:"xtkcd5"}]],j=o("list-ordered",f);/**
 * @license lucide-react v1.7.0 - ISC
 *
 * This source code is licensed under the ISC license.
 * See the LICENSE file in the root directory of this source tree.
 */const v=[["path",{d:"M3 5h.01",key:"18ugdj"}],["path",{d:"M3 12h.01",key:"nlz23k"}],["path",{d:"M3 19h.01",key:"noohij"}],["path",{d:"M8 5h13",key:"1pao27"}],["path",{d:"M8 12h13",key:"1za7za"}],["path",{d:"M8 19h13",key:"m83p4d"}]],M=o("list",v);function z({content:n,onChange:c,placeholder:s}){const t=a({extensions:[r.configure({heading:{levels:[2,3]}}),l.configure({placeholder:s||"Write something..."})],content:n,onUpdate:({editor:d})=>c(d.getHTML())});return t?e.jsxs("div",{className:"rounded-lg border border-surface-3 overflow-hidden bg-surface-0 focus-within:border-accent transition-colors",children:[e.jsxs("div",{className:"flex items-center gap-0.5 px-2 py-1 border-b border-surface-3",children:[e.jsx(i,{active:t.isActive("bold"),onClick:()=>t.chain().focus().toggleBold().run(),title:"Bold",children:e.jsx(x,{size:14})}),e.jsx(i,{active:t.isActive("italic"),onClick:()=>t.chain().focus().toggleItalic().run(),title:"Italic",children:e.jsx(k,{size:14})}),e.jsx("div",{className:"w-px h-4 bg-surface-3 mx-1"}),e.jsx(i,{active:t.isActive("heading",{level:2}),onClick:()=>t.chain().focus().toggleHeading({level:2}).run(),title:"Heading",children:e.jsx(y,{size:14})}),e.jsx(i,{active:t.isActive("bulletList"),onClick:()=>t.chain().focus().toggleBulletList().run(),title:"Bullet list",children:e.jsx(M,{size:14})}),e.jsx(i,{active:t.isActive("orderedList"),onClick:()=>t.chain().focus().toggleOrderedList().run(),title:"Ordered list",children:e.jsx(j,{size:14})})]}),e.jsx(h,{editor:t})]}):null}function i({active:n,onClick:c,title:s,children:t}){return e.jsx("button",{type:"button",onClick:c,title:s,className:`p-1.5 rounded transition-colors ${n?"bg-accent/15 text-accent":"text-content-dim hover:text-content hover:bg-surface-2"}`,children:t})}export{z as default};
