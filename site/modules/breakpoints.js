/**
 * The phone/desktop breakpoint contract: phone is 480px and under, desktop is
 * 481px and up. Every JS matchMedia read of the phone width uses PHONE_QUERY.
 * Two mirrors cannot import it: the classic script site/toolbar-fit.js (literal
 * '(max-width: 480px)') and the `@media (max-width: 480px)` / `(min-width: 481px)`
 * rules in site/style.css. Change all three together.
 */
export const PHONE_QUERY = '(max-width: 480px)';
