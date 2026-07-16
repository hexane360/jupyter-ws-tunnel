class s{messages=`Log:
`;elem=null;constructor(e=null){this.setElem(e)}setElem(e){this.elem=e,this.elem&&(this.elem.innerHTML=this.messages)}log(e){this.messages+=e+`
`,this.elem&&(this.elem.innerHTML=this.messages)}}new s(document.getElementById("ws-log"));
//# sourceMappingURL=main.js.map
