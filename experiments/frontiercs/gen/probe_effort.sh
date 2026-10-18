source ~/.zshrc >/dev/null 2>&1
CLI=/Users/toslali/Desktop/work/ibm/projects/llm-inference/study/inference-llmd/ai-native-method/_nous_paper/agentic-strategy-evolution/.venv/lib/python3.11/site-packages/claude_agent_sdk/_bundled/claude
Q='Without using any tools, compute the exact product 918273645546372819 x 564738291102938475 by hand, then verify it with a second independent method. Reply with only the final number.'
run(){ g=$1 u=$2 k=$3 m=$4 b=$5; d=/tmp/probe/$g-$(echo $m|tr / _)-${b:-none}; mkdir -p $d
  ( cd $d && env -u ANTHROPIC_AUTH_TOKEN ANTHROPIC_API_KEY=$k ANTHROPIC_BASE_URL=$u \
    timeout 900 $CLI -p "$Q" --model $m --output-format json --tools "" --effort $b > out.json 2>&1 ) ; }
for G in "vpc $NOUS_LITELLM_URL $NOUS_LITELLM_KEY1" "vpcint $NOUS_VPCINT_URL $NOUS_VPCINT_KEY2"; do set -- $G
  for m in claude-opus-4-6 aws/claude-opus-5 aws/claude-opus-5-5; do for b in medium low; do run $1 $2 $3 $m "$b" & done; done
done; wait
python3 - <<'PY'
import json,glob,os
for d in sorted(glob.glob("/tmp/probe/*")):
    key="-private"+d.replace("/","-").replace("_","-")
    tx=glob.glob(os.path.expanduser(f"~/.claude/projects/{key}/*.jsonl"))
    out=think=0; n=0
    for F in tx:
        seen={}
        for l in open(F):
            try:r=json.loads(l)
            except:continue
            m=r.get("message")
            if isinstance(m,dict) and m.get("usage") and m.get("id"):
                seen[m["id"]]=m["usage"].get("output_tokens",0)
                for b in m.get("content") or []:
                    if isinstance(b,dict) and b.get("type")=="thinking": think=max(think,len(b.get("thinking","")))
        out+=sum(seen.values()); n+=len(seen)
    try: res=str(json.load(open(d+"/out.json")).get("result"))[:40]
    except Exception: res=open(d+"/out.json").read()[-120:]
    print(os.path.basename(d), "transcripts",len(tx),"out_tokens",out,"thinking_chars",think,"result",res)
PY
