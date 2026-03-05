/** Simple SSML builder for engines that support it. */
export class SSMLBuilder {
  private parts: string[] = [];

  text(content: string): this {
    this.parts.push(escapeXml(content));
    return this;
  }

  emphasis(content: string, level: 'strong' | 'moderate' | 'reduced' = 'moderate'): this {
    this.parts.push(`<emphasis level="${level}">${escapeXml(content)}</emphasis>`);
    return this;
  }

  pause(ms: number): this {
    this.parts.push(`<break time="${ms}ms"/>`);
    return this;
  }

  prosody(content: string, attrs: { rate?: string; pitch?: string; volume?: string }): this {
    const attrStr = Object.entries(attrs)
      .filter(([, v]) => v !== undefined)
      .map(([k, v]) => `${k}="${v}"`)
      .join(' ');
    this.parts.push(`<prosody ${attrStr}>${escapeXml(content)}</prosody>`);
    return this;
  }

  phoneme(content: string, ipa: string): this {
    this.parts.push(`<phoneme alphabet="ipa" ph="${escapeXml(ipa)}">${escapeXml(content)}</phoneme>`);
    return this;
  }

  build(): string {
    return `<speak>${this.parts.join('')}</speak>`;
  }
}

function escapeXml(str: string): string {
  return str
    .replace(/&/g, '&amp;')
    .replace(/</g, '&lt;')
    .replace(/>/g, '&gt;')
    .replace(/"/g, '&quot;')
    .replace(/'/g, '&apos;');
}
