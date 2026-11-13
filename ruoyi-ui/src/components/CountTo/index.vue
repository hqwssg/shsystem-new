<template><span>{{ formatted }}</span></template>
<script>
export default {
  props: { startVal: { type: Number, default: 0 }, endVal: { type: Number, default: 0 }, duration: { type: Number, default: 1500 }, decimals: { type: Number, default: 0 }, separator: { type: String, default: ',' } },
  data() { return { value: this.startVal, animation: null } },
  computed: { formatted() { const parts = this.value.toFixed(this.decimals).split('.'); parts[0] = parts[0].replace(/\B(?=(\d{3})+(?!\d))/g, this.separator); return parts.join('.') } },
  watch: { endVal() { this.start() } }, mounted() { this.start() }, beforeUnmount() { cancelAnimationFrame(this.animation) },
  methods: { start() { cancelAnimationFrame(this.animation); const begin = performance.now(), from = this.startVal; const tick = now => { const t = this.duration <= 0 ? 1 : Math.min(1, (now-begin)/this.duration); this.value = from+(this.endVal-from)*t; if (t < 1) this.animation = requestAnimationFrame(tick) }; this.animation = requestAnimationFrame(tick) } }
}
</script>
