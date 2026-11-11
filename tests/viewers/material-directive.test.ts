import { createElement, type ReactElement } from 'react';
import { renderToStaticMarkup } from 'react-dom/server';
import { describe, expect, it } from 'vitest';
import { MaterialCard, parseMaterialMaps, registerMaterialCards } from '../../src/cards/material-card';

const uuid = 'aabbccdd-1234-5678-9abc-123456789abc';
const expected = {
  albedo: { asset: uuid }, normal: { path: '/normal.png' },
  metalness: { path: '/metal.png' }, heightmap: { path: '/height.png' },
};
function renderers() {
  const rows: any[] = [];
  const ctx = { register: (r: any) => { rows.push(r); return () => {}; } };
  registerMaterialCards(ctx as any, { webgl_limit: 2 });
  return {
    directive: (attrs: Record<string, unknown>, extra = {}) => rows.find(r => r.data.name === 'studiotwin-material').data.render({ attrs, source: 'original directive', streaming: false, sessionId: 'origin', ...extra }) as ReactElement<any> | null,
    media: (result: unknown) => rows.find(r => r.id === 'studiotwin-material-media').data.render({ toolName: 'mcp__studiotwin__text_to_material', result, file: { kind: 'image', name: 'albedo.png' }, fallback: 'native' }) as ReactElement<any>,
  };
}

describe('material map input normalization', () => {
  const input = { albedo: uuid, normals: '/normal.png', metallic: '/metal.png', height: '/height.png' };
  it.each([
    ['object', input], ['JSON', JSON.stringify(input)],
    ['comma equals', `albedo=${uuid}, normals=/normal.png, metallic=/metal.png, height=/height.png`],
    ['comma colon', `albedo:${uuid}, normals:/normal.png, metallic:/metal.png, height:/height.png`],
    ['URLSearchParams', new URLSearchParams(input)],
    ['query string', new URLSearchParams(input).toString()],
  ])('accepts %s with UUID sources and aliases', (_, value) => {
    expect(parseMaterialMaps(value)).toEqual(expected);
  });
  it('preserves explicit source objects and signed URL/path contents', () => {
    const url = 'https://cdn.example/a.png?sig=a%2Bb&part=2';
    expect(parseMaterialMaps({ albedo: { asset: uuid, name: 'paint' }, normal: url })).toEqual({
      albedo: { asset: uuid, name: 'paint' }, normal: { path: url },
    });
    expect(parseMaterialMaps(`albedo:${url},normal:/normal.png`)).toEqual({ albedo: { path: url }, normal: { path: '/normal.png' } });
    expect(parseMaterialMaps(`albedo=${url}`)).toEqual({ albedo: { path: url } });
    expect(parseMaterialMaps(new URLSearchParams({ albedo: url }).toString())).toEqual({ albedo: { path: url } });
  });
  it('uses aliases when a canonical property is undefined', () => {
    expect(parseMaterialMaps({ albedo: '/a.png', normal: undefined, normals: '/n.png', metalness: undefined, metallic: '/m.png' })).toEqual({ albedo: { path: '/a.png' }, normal: { path: '/n.png' }, metalness: { path: '/m.png' } });
  });
  it('gives canonical channels precedence regardless of property order', () => {
    for (const pair of [
      { normals: '/alias.png', normal: '/normal.png', metallic: '/alias.png', metalness: '/metal.png', height: '/alias.png', heightmap: '/height.png' },
      { normal: '/normal.png', normals: '/alias.png', metalness: '/metal.png', metallic: '/alias.png', heightmap: '/height.png', height: '/alias.png' },
    ]) expect(parseMaterialMaps({ albedo: uuid, ...pair })).toEqual(expected);
  });
  it.each([undefined, null, '', '{bad', [], { normal: '/normal.png' }, { albedo: '   ' }, { albedo: '/a.png', normal: '' }, { albedo: '/a.png', normal: 1 }, { albedo: { path: '/a', asset: uuid } }, { albedo: '/a', normal: '', normals: '/alias.png' }])('rejects invalid or incomplete input %#', value => {
    expect(() => parseMaterialMaps(value)).toThrow();
  });
});

describe('material transcript directive', () => {
  it('parses canonical flat syntax through the actual host regular expressions', () => {
    const source = `::studiotwin-material{albedo="${uuid}" normals="/normal.png" metallic="/metal.png" height="/height.png" name="Paint" zip="/maps.zip"}`;
    const DIRECTIVE_RE = /^::([a-z][a-z0-9-]{0,63})(?:\{([^{}]{0,1024})\})?$/;
    const ATTR_RE = /([a-z][\w-]{0,63})=(?:"([^"]*)"|'([^']*)')/gi;
    const match = DIRECTIVE_RE.exec(source);
    expect(match?.[1]).toBe('studiotwin-material');
    const attrs = Object.fromEntries([...match![2].matchAll(ATTR_RE)].map(m => [m[1], m[2] ?? m[3]]));
    const card = renderers().directive(attrs)!;
    expect(card.type).toBe(MaterialCard);
    expect(card.props).toMatchObject({ maps: expected, title: 'Paint', zip: { path: '/maps.zip' }, sessionId: 'origin', webgl_limit: 2 });
  });
  it.each([JSON.stringify({ albedo: '/nested.png' }), 'albedo=/nested.png', { albedo: '/nested.png' }])('prefers supplied maps over flat channels %#', maps => {
    const card = renderers().directive({ maps, albedo: '/flat.png', title: 'Explicit title', name: 'Other', zip: uuid })!;
    expect(card.type).toBe(MaterialCard);
    expect(card.props).toMatchObject({ maps: { albedo: { path: '/nested.png' } }, title: 'Explicit title', zip: { asset: uuid } });
  });
  it('keeps streamed incomplete and complete inputs null', () => {
    for (const attrs of [{}, { albedo: '/a.png' }, { maps: '{bad' }])
      expect(renderers().directive(attrs, { streaming: true })).toBeNull();
  });
  it.each([{}, { maps: '{bad', albedo: '/flat.png' }, { albedo: '' }])('returns original source paragraph after nonstreaming parse failure %#', attrs => {
    const fallback = renderers().directive(attrs)!;
    expect(fallback.type).toBe('p');
    expect(fallback.props.children).toBe('original directive');
  });
  it('renders a supplied title in the card header', () => {
    const html = renderToStaticMarkup(createElement(MaterialCard, { ctx: { rest: async () => ({}) } as any, maps: { albedo: { path: '/a.png' } }, ...{ title: 'Paint title' } }));
    expect(html).toContain('Paint title');
  });
});

it('normalizes aliases in tool media and preserves native fallback on malformed maps', () => {
  const { media } = renderers();
  for (const maps of [{ albedo: uuid, normals: '/normal.png', metallic: '/metal.png', height: '/height.png' }, `albedo=${uuid},normals=/normal.png,metallic=/metal.png,height=/height.png`]) {
    const card = media({ maps, name: 'Tool paint', zip: uuid });
    expect(card.type).toBe(MaterialCard);
    expect(card.props).toMatchObject({ maps: expected, title: 'Tool paint', zip: { asset: uuid } });
  }
  expect(media({ maps: '{bad' })).toBe('native');
});
