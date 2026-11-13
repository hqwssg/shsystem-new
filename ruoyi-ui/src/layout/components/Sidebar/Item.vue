<template>
  <svg-icon v-if="icon" :icon-class="icon" />
  <span v-if="title" :title="title.length > 5 ? title : undefined">{{ title }}</span>
</template>
<script>
export default { name: 'MenuItem', props: { icon: { type: String, default: '' }, title: { type: String, default: '' } } }
</script>
