#!/bin/sh
input=$(cat)

# one jq pass -> tab-separated fields
IFS='	' read -r dir model remaining five_hour seven_day pr_number pr_state <<EOF
$(echo "$input" | jq -r '[.workspace.current_dir, .model.display_name, (.context_window.remaining_percentage//""), (.rate_limits.five_hour.used_percentage//""), (.rate_limits.seven_day.used_percentage//""), (.pr.number//""), (.pr.review_state//"")] | @tsv')
EOF

base=$(basename "$dir")
branch=$(cd "$dir" 2>/dev/null && git --no-optional-locks rev-parse --abbrev-ref HEAD 2>/dev/null)
dirty=$(cd "$dir" 2>/dev/null && git --no-optional-locks status --porcelain 2>/dev/null | head -n 1)

# muted palette (xterm-256)
C_GREEN=108; C_YELLOW=179; C_RED=167
C_DIR=73; C_BRANCH=131; C_MODEL=139; C_SPIN=67
C_LABEL=243; C_TRACK=236; C_SHIMMER=250

# animation tick: ~5 fps via hi-res time, fall back to whole seconds
tick=$(perl -MTime::HiRes=time -e 'print int(Time::HiRes::time()*5)' 2>/dev/null)
[ -z "$tick" ] && tick=$(date +%s)

# progress bar.  $1 percent  $2 width  $3 shimmer-cell (-1=none)  $4 solid color (""=ramp)
bar() {
  awk -v p="$1" -v w="$2" -v sh="$3" -v solid="$4" -v glint="$C_SHIMMER" -v trk="$C_TRACK" 'BEGIN{
    e[1]="▏";e[2]="▎";e[3]="▍";e[4]="▌";e[5]="▋";e[6]="▊";e[7]="▉";e[8]="█";
    r[1]=108;r[2]=108;r[3]=109;r[4]=143;r[5]=144;r[6]=179;r[7]=179;r[8]=173;r[9]=167;r[10]=167;
    if(p<0)p=0; if(p>100)p=100;
    filled=p/100.0*w; out=sprintf("\033[38;5;%dm▕\033[0m",trk);
    for(i=1;i<=w;i++){
      pos=int((i-0.5)/w*10)+1; if(pos<1)pos=1; if(pos>10)pos=10;
      col=(solid==""?r[pos]:solid);
      cf=filled-(i-1);
      if(cf>=1){
        if((i-1)==sh) out=out sprintf("\033[38;5;%dm█\033[0m",glint);
        else out=out sprintf("\033[38;5;%dm█\033[0m",col);
      } else if(cf<=0){
        out=out sprintf("\033[38;5;%dm░\033[0m",trk);
      } else {
        x=int(cf*8+0.5); if(x<1)x=1; if(x>8)x=8;
        out=out sprintf("\033[38;5;%dm%s\033[0m",col,e[x]);
      }
    }
    printf "%s\033[38;5;%dm▏\033[0m", out, trk;
  }'
}

round() { printf '%.0f' "$1"; }

printf '\033[38;5;%dm➜\033[0m  \033[38;5;%dm%s\033[0m' "$C_GREEN" "$C_DIR" "$base"
if [ -n "$branch" ]; then
  printf ' \033[38;5;%dmgit:(\033[38;5;%dm%s\033[38;5;%dm)\033[0m' "$C_LABEL" "$C_BRANCH" "$branch" "$C_LABEL"
  if [ -n "$dirty" ]; then printf '\033[38;5;%dm✗\033[0m' "$C_RED"; else printf '\033[38;5;%dm✓\033[0m' "$C_GREEN"; fi
fi
if [ -n "$pr_number" ]; then
  if [ -n "$pr_state" ]; then
    case "$pr_state" in
      approved|APPROVED) sc=$C_GREEN ;;
      changes_requested|CHANGES_REQUESTED) sc=$C_RED ;;
      *) sc=$C_YELLOW ;;
    esac
    printf ' \033[38;5;%dmPR#\033[38;5;%dm%s\033[38;5;%dm(\033[38;5;%dm%s\033[38;5;%dm)\033[0m' "$C_LABEL" "$C_YELLOW" "$pr_number" "$C_LABEL" "$sc" "$pr_state" "$C_LABEL"
  else
    printf ' \033[38;5;%dmPR#\033[38;5;%dm%s\033[0m' "$C_LABEL" "$C_YELLOW" "$pr_number"
  fi
fi

# soft braille spinner before the model
spin=$(awk -v f="$((tick % 10))" 'BEGIN{split("⠋|⠙|⠹|⠸|⠼|⠴|⠦|⠧|⠇|⠏",a,"|");printf "%s",a[f+1]}')
printf ' \033[38;5;%dm%s\033[0m \033[38;5;%dm[%s]\033[0m' "$C_SPIN" "$spin" "$C_MODEL" "$model"

# context: pie glyph + solid threshold-colored bar
if [ -n "$remaining" ]; then
  rem=$(round "$remaining")
  if [ "$rem" -ge 50 ]; then cc=$C_GREEN; elif [ "$rem" -ge 20 ]; then cc=$C_YELLOW; else cc=$C_RED; fi
  pie=$(awk -v p="$rem" 'BEGIN{if(p>=88)c="●";else if(p>=63)c="◕";else if(p>=38)c="◑";else if(p>=13)c="◔";else c="○";printf "%s",c}')
  printf '  \033[38;5;%dm%s\033[0m %s\033[38;5;%dm%s%%\033[0m' "$cc" "$pie" "$(bar "$rem" 12 "$((tick % 12))" "$cc")" "$cc" "$rem"
fi

# rate limits: muted green->red gradient bars
if [ -n "$five_hour" ]; then
  v=$(round "$five_hour")
  printf '  \033[38;5;%dm5h\033[0m %s\033[38;5;%dm%s%%\033[0m' "$C_LABEL" "$(bar "$v" 8 "$((tick % 8))" "")" "$C_LABEL" "$v"
fi
if [ -n "$seven_day" ]; then
  v=$(round "$seven_day")
  printf '  \033[38;5;%dm7d\033[0m %s\033[38;5;%dm%s%%\033[0m' "$C_LABEL" "$(bar "$v" 8 "$(((tick + 4) % 8))" "")" "$C_LABEL" "$v"
fi
printf '\n'
