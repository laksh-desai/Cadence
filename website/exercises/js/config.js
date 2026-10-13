/*
 * SD Mobile PT – Exercises: settings you may want to change.
 *
 * LOGIN
 *   The program builder asks for this username and password. Change them here, save the file,
 *   then re-publish the site. The username is not case-sensitive; the password is.
 *
 *   Important: this is a simple "staff only" gate that runs in the browser. It keeps casual
 *   visitors out of the builder, but it is not strong security (anyone technical can read this
 *   file). Never store patient health records in this app. Patient handout links (…#p=…) do
 *   not ask for the login, so patients can open what you send them.
 */
window.HEP_CONFIG = {
  username: 'SDMPT',
  password: 'Exercises',

  // Where the "Back to website" link on the login page goes.
  websiteUrl: 'https://www.sdmobilept.com/',

  // Starting clinic details for handouts (each user can still change them under Settings).
  clinic: 'SD Mobile PT',
  phone: '619-289-7110',
  contact: 'info@sdmobilept.com'
};
