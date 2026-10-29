#!/usr/bin/env bash
# set-loudness.sh in.wav out.(wav|mp3|m4a) [target LUFS, default -14] [limiter ceiling in dB, default -1.5]
#
# Mono, one fixed gain and a peak limiter, landed on the target loudness. It finds the gain by trying, because
# the limiter takes a little loudness away. Then it measures the true peak of the encoded file. A bright voice
# overshoots more in AAC than a dull one (0.9 dB on the mastered walk, at any bitrate, and it moves by a tenth
# or two from one encode to the next). While the encoded peak is over -1.0 dBTP the output is turned down after
# the limiter: the walk then sits a few tenths under the target loudness, and the voice is not limited any
# harder. YouTube plays a quieter file as it is.
#
# The last line printed is the filter chain to use in the real encode.
#
# AAC is encoded with -aac_tns 0, and the real encode must use it too (2026-10-14). On walk 0035 ffmpeg's own AAC
# encoder, with its temporal noise shaping on, put one frame of ordinary speech 4.3 dB over the limiter (+2.8 dBTP)
# and the trim above would have dropped the whole walk to -18 LUFS. With TNS off the worst peak was -1.09 dBTP,
# the sound stayed in step, and the coding error was lower in every band.
in="$1"; out="$2"; T="${3:--14}"; C="${4:--1.5}"; G=7.5
L=$(awk "BEGIN{printf \"%.4f\", 10 ^ ($C / 20)}")
chain() { echo "volume=${1}dB,aresample=192000,alimiter=limit=${L}:attack=5:release=50:level=false:latency=true,aresample=48000"; }
case "$out" in
  *.mp3) codec="-c:a libmp3lame -b:a 256k" ;;
  *.m4a) codec="-c:a aac -b:a 192k -aac_tns 0" ;;
  *)     codec="-c:a pcm_s16le" ;;
esac
for i in 1 2 3 4 5 6 7 8; do
  I=$(ffmpeg -hide_banner -nostats -i "$in" -af "$(chain $G),loudnorm=print_format=json" -f null - 2>&1 | grep '"input_i"' | grep -oE -- '-?[0-9]+\.[0-9]+')
  D=$(awk "BEGIN{printf \"%.3f\", $T - ($I)}")
  if awk "BEGIN{exit !($D < 0.03 && $D > -0.03)}"; then break; fi
  G=$(awk "BEGIN{printf \"%.2f\", $G + $D * 1.3}")
done
TRIM=0
for round in 1 2 3 4 5; do
  F="$(chain $G)"
  if awk "BEGIN{exit !($TRIM > 0)}"; then F="$F,volume=-${TRIM}dB"; fi
  ffmpeg -hide_banner -nostats -v error -y -i "$in" -af "$F" -ar 48000 -ac 1 $codec "$out"
  M=$(ffmpeg -hide_banner -nostats -i "$out" -af "ebur128=peak=true:framelog=quiet" -f null - 2>&1)
  P=$(echo "$M" | grep "Peak:" | grep -oE -- '-?[0-9]+\.[0-9]+' | tail -1)
  echo "$(basename "$out"): trim ${TRIM} dB ->$(echo "$M" | grep -E " I:|Peak:" | tr -s ' ' | tr '\n' ' ')"
  if awk "BEGIN{exit !($P <= -1.0)}"; then break; fi
  TRIM=$(awk "BEGIN{printf \"%.2f\", $TRIM + ($P + 1.0) + 0.15}")
done
echo "$F"
